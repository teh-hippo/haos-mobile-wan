import io
import json
import unittest
import urllib.error
import urllib.request

from helpers import make_config
from rootfs.app.const import IPHONE_USB, IPHONE_USB_WIFI_FALLBACK
from rootfs.app.hotspot import (
    WIFI_ADAPTER_DISABLED,
    WIFI_NOT_ASSOCIATED,
    classify_wifi_upstream,
    interface_status,
    provision_hotspot,
)


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


class _FakeInfoResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body


def _info_urlopen(payload: object) -> tuple[object, dict[str, object]]:
    captured: dict[str, object] = {}

    def urlopen(request, **kwargs):
        captured["request"] = request
        captured["timeout"] = kwargs.get("timeout")
        return _FakeInfoResponse(json.dumps(payload).encode())

    return urlopen, captured


def _wifi_config():
    return make_config(hotspot_ssid="Phone", hotspot_password="supersecret")


class InterfaceStatusTests(unittest.TestCase):
    def test_returns_data_for_disabled_adapter(self) -> None:
        urlopen, _ = _info_urlopen(
            {"result": "ok", "data": {"enabled": False, "connected": False}}
        )
        data = interface_status(_wifi_config(), token="token", urlopen=urlopen)
        self.assertEqual(data, {"enabled": False, "connected": False})

    def test_returns_data_for_enabled_not_associated(self) -> None:
        urlopen, _ = _info_urlopen(
            {"result": "ok", "data": {"enabled": True, "connected": False}}
        )
        data = interface_status(_wifi_config(), token="token", urlopen=urlopen)
        self.assertEqual(data, {"enabled": True, "connected": False})

    def test_returns_data_for_connected_interface(self) -> None:
        urlopen, _ = _info_urlopen(
            {"result": "ok", "data": {"enabled": True, "connected": True}}
        )
        data = interface_status(_wifi_config(), token="token", urlopen=urlopen)
        self.assertEqual(data, {"enabled": True, "connected": True})

    def test_gets_info_endpoint_with_bearer_token(self) -> None:
        urlopen, captured = _info_urlopen({"result": "ok", "data": {}})
        interface_status(_wifi_config(), token="token", urlopen=urlopen)
        request = captured["request"]
        assert isinstance(request, urllib.request.Request)
        self.assertEqual(
            request.full_url,
            "http://supervisor/network/interface/wlan0/info",
        )
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer token")
        self.assertEqual(captured["timeout"], 10)

    def test_missing_token_does_not_call_supervisor(self) -> None:
        calls: list[urllib.request.Request] = []
        data = interface_status(
            _wifi_config(),
            token="",
            urlopen=lambda request, **kwargs: calls.append(request),
        )
        self.assertIsNone(data)
        self.assertEqual(calls, [])

    def test_supervisor_url_error_returns_none(self) -> None:
        def urlopen(request, **kwargs):
            raise urllib.error.URLError("supervisor down")

        data = interface_status(_wifi_config(), token="token", urlopen=urlopen)
        self.assertIsNone(data)

    def test_http_error_returns_none(self) -> None:
        def urlopen(request, **kwargs):
            raise urllib.error.HTTPError(
                request.full_url, 404, "Not Found", {}, io.BytesIO(b"")
            )

        data = interface_status(_wifi_config(), token="token", urlopen=urlopen)
        self.assertIsNone(data)

    def test_malformed_json_returns_none(self) -> None:
        def urlopen(request, **kwargs):
            return _FakeInfoResponse(b"not json")

        data = interface_status(_wifi_config(), token="token", urlopen=urlopen)
        self.assertIsNone(data)

    def test_non_dict_data_returns_none(self) -> None:
        urlopen, _ = _info_urlopen({"result": "ok", "data": "unexpected"})
        data = interface_status(_wifi_config(), token="token", urlopen=urlopen)
        self.assertIsNone(data)


class ClassifyWifiUpstreamTests(unittest.TestCase):
    def test_disabled_adapter_replaces_generic_error(self) -> None:
        errors = classify_wifi_upstream(
            _wifi_config(),
            ["Upstream interface/address is not active"],
            lambda: {"enabled": False, "connected": False},
        )
        self.assertEqual(errors, [WIFI_ADAPTER_DISABLED])

    def test_enabled_not_associated_replaces_generic_error(self) -> None:
        errors = classify_wifi_upstream(
            _wifi_config(),
            ["Upstream interface/address is not active"],
            lambda: {"enabled": True, "connected": False},
        )
        self.assertEqual(errors, [WIFI_NOT_ASSOCIATED])

    def test_unavailable_error_is_also_classified(self) -> None:
        errors = classify_wifi_upstream(
            _wifi_config(),
            ["Upstream interface is unavailable"],
            lambda: {"enabled": False, "connected": False},
        )
        self.assertEqual(errors, [WIFI_ADAPTER_DISABLED])

    def test_connected_interface_keeps_generic_error(self) -> None:
        errors = classify_wifi_upstream(
            _wifi_config(),
            ["Upstream interface/address is not active"],
            lambda: {"enabled": True, "connected": True},
        )
        self.assertEqual(errors, ["Upstream interface/address is not active"])

    def test_supervisor_unavailable_keeps_generic_error(self) -> None:
        errors = classify_wifi_upstream(
            _wifi_config(),
            ["Upstream interface/address is not active"],
            lambda: None,
        )
        self.assertEqual(errors, ["Upstream interface/address is not active"])

    def test_other_errors_are_preserved(self) -> None:
        errors = classify_wifi_upstream(
            _wifi_config(),
            [
                "Host IPv4 forwarding is not enabled",
                "Upstream interface/address is not active",
            ],
            lambda: {"enabled": False, "connected": False},
        )
        self.assertEqual(
            errors,
            ["Host IPv4 forwarding is not enabled", WIFI_ADAPTER_DISABLED],
        )

    def test_reader_not_called_without_generic_error(self) -> None:
        calls: list[bool] = []

        def reader() -> dict[str, object]:
            calls.append(True)
            return {"enabled": False}

        errors = classify_wifi_upstream(
            _wifi_config(),
            ["Host IPv4 forwarding is not enabled"],
            reader,
        )
        self.assertEqual(errors, ["Host IPv4 forwarding is not enabled"])
        self.assertEqual(calls, [])

    def test_reader_not_called_without_credentials(self) -> None:
        calls: list[bool] = []

        def reader() -> dict[str, object]:
            calls.append(True)
            return {"enabled": False}

        errors = classify_wifi_upstream(
            make_config(),
            ["Upstream interface/address is not active"],
            reader,
        )
        self.assertEqual(errors, ["Upstream interface/address is not active"])
        self.assertEqual(calls, [])

    def test_reader_not_called_for_usb_mode(self) -> None:
        calls: list[bool] = []

        def reader() -> dict[str, object]:
            calls.append(True)
            return {"enabled": False}

        errors = classify_wifi_upstream(
            make_config(
                mobile_connection=IPHONE_USB,
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            ["Upstream interface/address is not active"],
            reader,
        )
        self.assertEqual(errors, ["Upstream interface/address is not active"])
        self.assertEqual(calls, [])

    def test_fallback_mode_classifies_wifi_fault(self) -> None:
        errors = classify_wifi_upstream(
            make_config(
                mobile_connection=IPHONE_USB_WIFI_FALLBACK,
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            ["Upstream interface/address is not active"],
            lambda: {"enabled": True, "connected": False},
        )
        self.assertEqual(errors, [WIFI_NOT_ASSOCIATED])


if __name__ == "__main__":
    unittest.main()
