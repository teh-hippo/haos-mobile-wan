import json
import tempfile
import unittest
from pathlib import Path

from rootfs.app.config import FALLBACK_MANAGEMENT, GatewayConfig
from rootfs.app.errors import GatewayError

from helpers import FakeRunner, make_config


class GatewayConfigTests(unittest.TestCase):
    def test_reads_reduced_options_and_detects_management(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "options.json"
            path.write_text(
                json.dumps(
                    {
                        "mode": "disabled",
                        "dry_run": True,
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
            self.assertEqual(config.upstream_mode, "hotspot_wifi")

    def test_rejects_non_object_options(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "options.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(GatewayError, "must be an object"):
                GatewayConfig.from_path(path, run=lambda *args: FakeRunner().run(list(args)))

    def test_load_path_degrades_when_management_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "options.json"
            path.write_text('{"mode":"active"}', encoding="utf-8")
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
                '{"mode":"active","downstream_address":"203.0.113.1/24"}',
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

            self.assertEqual(config.mode, "disabled")
            self.assertEqual(config.downstream_address, "192.168.80.1/24")
            self.assertIn("Invalid app configuration", error)

    def test_rejects_invalid_upstream_mode(self) -> None:
        config = make_config(upstream_mode="not-real")
        with self.assertRaisesRegex(GatewayError, "Unsupported upstream mode"):
            config.validate()

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

    def test_usb_mode_allows_dynamic_upstream_network(self) -> None:
        config = make_config(
            upstream_mode="iphone_usb",
            upstream_interface="wlan0",
            upstream_address="0.0.0.0/32",
            upstream_gateway="0.0.0.0",
        )
        config.validate()


if __name__ == "__main__":
    unittest.main()
