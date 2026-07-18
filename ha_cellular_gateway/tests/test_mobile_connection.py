import unittest

from helpers import make_config
from rootfs.app.const import (
    IPHONE_USB,
    IPHONE_USB_WIFI_FALLBACK,
    WIFI_HOTSPOT,
)
from rootfs.app.mobile_connection import MobileConnectionResolver
from rootfs.app.networkmanager import NetworkManagerResult
from rootfs.app.upstream_models import ResolvedUpstream


class StubIPhone:
    def __init__(
        self,
        results: list[tuple[ResolvedUpstream | None, list[str]]],
    ) -> None:
        self.results = results
        self.calls = 0
        self.fallback_safe = True
        self.pairing_message: str | None = None

    def resolve(
        self,
        management: object = None,
    ) -> tuple[ResolvedUpstream | None, list[str]]:
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        return result

    def fallback_allowed(self) -> bool:
        return self.fallback_safe


class StubWifi:
    def __init__(self, results: list[NetworkManagerResult]) -> None:
        self.results = results
        self.calls = 0

    def inspect(self) -> NetworkManagerResult:
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        return result


def usb_upstream() -> ResolvedUpstream:
    return ResolvedUpstream(
        connection=IPHONE_USB,
        interface="eth0",
        address="172.20.10.2/28",
        gateway="172.20.10.1",
    )


def wifi_upstream() -> ResolvedUpstream:
    return ResolvedUpstream(
        connection=WIFI_HOTSPOT,
        interface="wlan0",
        address="172.20.10.4/28",
        gateway="172.20.10.1",
    )


def wifi_active() -> NetworkManagerResult:
    return NetworkManagerResult(wifi_upstream(), "active", None, True)


def wifi_waiting() -> NetworkManagerResult:
    return NetworkManagerResult(
        None,
        "waiting",
        "Hotspot Wi-Fi is enabled but not associated",
        True,
    )


class MobileConnectionResolverTests(unittest.TestCase):
    def test_wifi_connection_does_not_resolve_usb(self) -> None:
        iphone = StubIPhone([(None, ["not connected"])])
        resolution = MobileConnectionResolver(
            make_config(mobile_connection=WIFI_HOTSPOT),
            iphone,
            StubWifi([wifi_active()]),
        ).resolve()

        assert resolution.upstream is not None
        self.assertEqual(resolution.upstream.connection, WIFI_HOTSPOT)
        self.assertEqual(iphone.calls, 0)

    def test_usb_connection_reports_usb_errors(self) -> None:
        resolution = MobileConnectionResolver(
            make_config(mobile_connection=IPHONE_USB),
            StubIPhone([(None, ["waiting for trust"])]),
            StubWifi([wifi_waiting()]),
        ).resolve()

        self.assertIsNone(resolution.upstream)
        self.assertEqual(resolution.errors, ("waiting for trust",))
        self.assertFalse(resolution.fallback_active)

    def test_combined_connection_prefers_ready_usb(self) -> None:
        wifi = StubWifi([wifi_active()])
        resolution = MobileConnectionResolver(
            make_config(mobile_connection=IPHONE_USB_WIFI_FALLBACK),
            StubIPhone([(usb_upstream(), [])]),
            wifi,
        ).resolve()

        self.assertEqual(resolution.upstream, usb_upstream())
        self.assertFalse(resolution.fallback_active)
        self.assertIsNone(resolution.fallback_reason)
        self.assertEqual(wifi.calls, 1)

    def test_combined_connection_falls_back_to_wifi(self) -> None:
        resolution = MobileConnectionResolver(
            make_config(mobile_connection=IPHONE_USB_WIFI_FALLBACK),
            StubIPhone([(None, ["waiting for device"])]),
            StubWifi([wifi_active()]),
        ).resolve()

        assert resolution.upstream is not None
        self.assertEqual(resolution.upstream.connection, WIFI_HOTSPOT)
        self.assertEqual(resolution.errors, ())
        self.assertTrue(resolution.fallback_active)
        self.assertEqual(resolution.fallback_reason, "waiting for device")

    def test_combined_connection_blocks_unsafe_usb_state(self) -> None:
        iphone = StubIPhone([(None, ["USB ownership conflict"])])
        iphone.fallback_safe = False
        iphone.pairing_message = "USB ownership conflict"
        resolution = MobileConnectionResolver(
            make_config(mobile_connection=IPHONE_USB_WIFI_FALLBACK),
            iphone,
            StubWifi([wifi_active()]),
        ).resolve()

        self.assertIsNone(resolution.upstream)
        self.assertEqual(resolution.errors, ("USB ownership conflict",))
        self.assertFalse(resolution.fallback_active)

    def test_wifi_ownership_error_blocks_both_paths(self) -> None:
        ready = MobileConnectionResolver(
            make_config(mobile_connection=IPHONE_USB_WIFI_FALLBACK),
            StubIPhone([(usb_upstream(), [])]),
            StubWifi([wifi_active()]),
            wifi_error="Hotspot Wi-Fi provisioning failed: rejected",
        ).resolve()
        fallback = MobileConnectionResolver(
            make_config(mobile_connection=IPHONE_USB_WIFI_FALLBACK),
            StubIPhone([(None, ["waiting for device"])]),
            StubWifi([wifi_waiting()]),
            wifi_error="Hotspot Wi-Fi provisioning failed: rejected",
        ).resolve()

        self.assertEqual(
            ready.errors,
            ("Hotspot Wi-Fi provisioning failed: rejected",),
        )
        self.assertEqual(
            fallback.errors,
            ("Hotspot Wi-Fi provisioning failed: rejected",),
        )

    def test_combined_connection_returns_to_usb(self) -> None:
        iphone = StubIPhone(
            [
                (None, ["waiting for device"]),
                (usb_upstream(), []),
            ]
        )
        resolver = MobileConnectionResolver(
            make_config(mobile_connection=IPHONE_USB_WIFI_FALLBACK),
            iphone,
            StubWifi([wifi_active(), wifi_active()]),
        )

        fallback = resolver.resolve()
        recovered = resolver.resolve()

        self.assertTrue(fallback.fallback_active)
        self.assertEqual(recovered.upstream, usb_upstream())
        self.assertFalse(recovered.fallback_active)


if __name__ == "__main__":
    unittest.main()
