import json
import tempfile
import unittest
from pathlib import Path

from rootfs.app.config import FALLBACK_MANAGEMENT, GatewayConfig
from rootfs.app.const import (
    IPHONE_USB,
    IPHONE_USB_WIFI_FALLBACK,
    WIFI_HOTSPOT,
)
from rootfs.app.errors import GatewayError

from helpers import FakeRunner, make_config


class GatewayConfigTests(unittest.TestCase):
    def test_reads_reduced_options_and_detects_management(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "options.json"
            path.write_text(
                json.dumps(
                    {
                        "enabled": False,
                        "mobile_connection": "Wi-Fi hotspot",
                        "downstream_mac": "00:11:22:33:44:55",
                    }
                ),
                encoding="utf-8",
            )
            runner = FakeRunner()
            config = GatewayConfig.from_path(
                path,
                run=lambda *args, **kwargs: runner.run(
                    list(args),
                    check=kwargs.get("check", True),
                    timeout=kwargs.get("timeout", 20),
                ),
            )
            self.assertEqual(config.management_interface, "end0")
            self.assertEqual(config.management_address, "192.168.1.2/24")
            self.assertEqual(config.transit_subnet, "192.168.80.0/24")
            self.assertEqual(config.dhcp_start, "192.168.80.2")
            self.assertEqual(config.dhcp_end, "192.168.80.2")
            self.assertFalse(config.enabled)
            self.assertEqual(config.mobile_connection, WIFI_HOTSPOT)

    def test_rejects_non_object_options(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "options.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(GatewayError, "must be an object"):
                GatewayConfig.from_path(path, run=lambda *args: FakeRunner().run(list(args)))

    def test_load_path_degrades_when_management_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "options.json"
            path.write_text('{"enabled":true}', encoding="utf-8")
            runner = FakeRunner()
            runner.main_default_routes = []

            config, error = GatewayConfig.load_path(
                path,
                run=lambda *args, **kwargs: runner.run(
                    list(args),
                    check=kwargs.get("check", True),
                    timeout=kwargs.get("timeout", 20),
                ),
            )

            self.assertEqual(
                config.management_interface,
                FALLBACK_MANAGEMENT.interface,
            )
            self.assertIn("Cannot detect management network", error)

    def test_load_path_uses_safe_defaults_for_invalid_options(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "options.json"
            path.write_text(
                '{"enabled":true,"router_address":"203.0.113.1/24"}',
                encoding="utf-8",
            )

            config, error = GatewayConfig.load_path(
                path,
                run=lambda *args, **kwargs: FakeRunner().run(
                    list(args),
                    check=kwargs.get("check", True),
                    timeout=kwargs.get("timeout", 20),
                ),
            )

            self.assertFalse(config.enabled)
            self.assertEqual(config.downstream_address, "192.168.80.1/24")
            self.assertIn("Invalid app configuration", error)

    def test_rejects_invalid_mobile_connection(self) -> None:
        config = make_config(mobile_connection="not-real")
        with self.assertRaisesRegex(GatewayError, "Unsupported mobile connection"):
            config.validate()

    def test_maps_friendly_mobile_connection_choices(self) -> None:
        expected = {
            "Wi-Fi hotspot": WIFI_HOTSPOT,
            "USB (iPhone)": IPHONE_USB,
            "USB (iPhone), Wi-Fi fallback": IPHONE_USB_WIFI_FALLBACK,
        }
        for option, connection in expected.items():
            with self.subTest(option=option):
                config = GatewayConfig._from_data(
                    {"mobile_connection": option},
                    FALLBACK_MANAGEMENT,
                )
                self.assertEqual(config.mobile_connection, connection)

    def test_rejects_overlapping_networks(self) -> None:
        config = make_config(downstream_address="192.168.1.10/25")
        with self.assertRaisesRegex(GatewayError, "must not overlap"):
            config.validate()

    def test_rejects_public_downstream_network(self) -> None:
        config = make_config(downstream_address="203.0.113.1/24")
        with self.assertRaisesRegex(GatewayError, "private IPv4"):
            config.validate()

    def test_rejects_downstream_without_router_lease(self) -> None:
        config = make_config(downstream_address="192.168.80.0/31")
        with self.assertRaisesRegex(GatewayError, "usable host|router lease"):
            config.validate()

    def test_derives_single_router_lease_when_gateway_is_not_first(self) -> None:
        config = make_config(downstream_address="192.168.80.2/30")
        config.validate()
        self.assertEqual(config.dhcp_start, "192.168.80.1")
        self.assertEqual(config.dhcp_end, "192.168.80.1")

    def test_rejects_invalid_mac(self) -> None:
        config = make_config(downstream_mac="not-a-mac")
        with self.assertRaisesRegex(GatewayError, "MAC address"):
            config.validate()

    def test_accepts_empty_hotspot_credentials(self) -> None:
        make_config(hotspot_ssid="", hotspot_password="").validate()

    def test_requires_hotspot_ssid_and_password_together(self) -> None:
        for overrides in (
            {"hotspot_ssid": "Phone", "hotspot_password": ""},
            {"hotspot_ssid": "", "hotspot_password": "validpass"},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(GatewayError, "both be set"):
                    make_config(**overrides).validate()

    def test_validates_hotspot_ssid_wifi_limits(self) -> None:
        with self.assertRaisesRegex(GatewayError, "SSID"):
            make_config(hotspot_ssid="x" * 33, hotspot_password="validpass").validate()
        make_config(hotspot_ssid="Phone", hotspot_password="validpass").validate()

    def test_validates_hotspot_password_length(self) -> None:
        for password in ("short", "x" * 64):
            with self.subTest(password=password):
                with self.assertRaisesRegex(GatewayError, "password"):
                    make_config(hotspot_ssid="Phone", hotspot_password=password).validate()

    def test_usb_connection_allows_dynamic_upstream_network(self) -> None:
        config = make_config(
            mobile_connection=IPHONE_USB,
            upstream_interface="wlan0",
            upstream_address="0.0.0.0/32",
            upstream_gateway="0.0.0.0",
        )
        config.validate()


if __name__ == "__main__":
    unittest.main()
