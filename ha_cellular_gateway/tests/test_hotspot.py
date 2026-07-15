import io
import json
import unittest
import urllib.error
import urllib.request

from helpers import make_config
from rootfs.app.const import IPHONE_USB, IPHONE_USB_WIFI_FALLBACK
from rootfs.app.hotspot import provision_hotspot


class HotspotProvisioningTests(unittest.TestCase):
    def test_empty_credentials_do_not_call_supervisor(self) -> None:
        calls: list[urllib.request.Request] = []
        error = provision_hotspot(
            make_config(),
            token="token",
            urlopen=lambda request, **kwargs: calls.append(request),
        )
        self.assertIsNone(error)
        self.assertEqual(calls, [])

    def test_iphone_usb_does_not_call_supervisor(self) -> None:
        calls: list[urllib.request.Request] = []
        error = provision_hotspot(
            make_config(
                mobile_connection=IPHONE_USB,
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            token="token",
            urlopen=lambda request, **kwargs: calls.append(request),
        )
        self.assertIsNone(error)
        self.assertEqual(calls, [])

    def test_combined_connection_provisions_wifi(self) -> None:
        calls: list[urllib.request.Request] = []
        error = provision_hotspot(
            make_config(
                mobile_connection=IPHONE_USB_WIFI_FALLBACK,
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            token="token",
            urlopen=lambda request, **kwargs: calls.append(request),
        )
        self.assertIsNone(error)
        self.assertEqual(len(calls), 1)

    def test_sends_exact_supervisor_payload(self) -> None:
        captured: dict[str, object] = {}

        def urlopen(request, **kwargs):
            captured["request"] = request
            captured["timeout"] = kwargs["timeout"]
            return object()

        error = provision_hotspot(
            make_config(
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            token="token",
            urlopen=urlopen,
        )

        self.assertIsNone(error)
        request = captured["request"]
        assert isinstance(request, urllib.request.Request)
        self.assertEqual(
            request.full_url,
            "http://supervisor/network/interface/wlan0/update",
        )
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer token")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(captured["timeout"], 10)
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {
                "enabled": True,
                "ipv4": {
                    "method": "static",
                    "address": ["172.20.10.4/28"],
                    "nameservers": ["1.1.1.1", "8.8.8.8"],
                },
                "ipv6": {"method": "disabled"},
                "wifi": {
                    "mode": "infrastructure",
                    "auth": "wpa-psk",
                    "ssid": "Phone",
                    "psk": "supersecret",
                },
            },
        )

    def test_supervisor_error_is_safe_and_focused(self) -> None:
        body = json.dumps(
            {"message": "could not apply profile with password supersecret"}
        ).encode()

        def urlopen(request, **kwargs):
            raise urllib.error.HTTPError(
                request.full_url,
                400,
                "Bad Request",
                {},
                io.BytesIO(body),
            )

        error = provision_hotspot(
            make_config(
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            token="token",
            urlopen=urlopen,
        )

        assert error is not None
        self.assertIn("Hotspot Wi-Fi provisioning failed", error)
        self.assertIn("Supervisor network API rejected the update", error)
        self.assertNotIn("supersecret", error)
        self.assertNotIn("psk", error)
        self.assertNotIn("172.20.10.4/28", error)


if __name__ == "__main__":
    unittest.main()
