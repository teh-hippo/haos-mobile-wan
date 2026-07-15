import json
import tempfile
import unittest
from pathlib import Path

from rootfs.app.config import GatewayConfig
from rootfs.app.errors import GatewayError

from helpers import make_config


class GatewayConfigTests(unittest.TestCase):
    def test_reads_options(self) -> None:
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
            config = GatewayConfig.from_path(path)
            self.assertEqual(config.transit_subnet, "192.168.80.0/24")
            self.assertEqual(config.upstream_mode, "hotspot_wifi")

    def test_rejects_invalid_upstream_mode(self) -> None:
        config = make_config(upstream_mode="not-real")
        with self.assertRaisesRegex(GatewayError, "Unsupported upstream mode"):
            config.validate()

    def test_rejects_overlapping_networks(self) -> None:
        config = make_config(
            downstream_address="192.168.1.10/25",
            transit_subnet="192.168.1.0/25",
            dhcp_start="192.168.1.20",
            dhcp_end="192.168.1.30",
        )
        with self.assertRaisesRegex(GatewayError, "must not overlap"):
            config.validate()

    def test_rejects_mismatched_downstream_prefix(self) -> None:
        config = make_config(downstream_address="192.168.80.1/25")
        with self.assertRaisesRegex(GatewayError, "transit subnet prefix"):
            config.validate()

    def test_rejects_invalid_transit_subnet(self) -> None:
        config = make_config(transit_subnet="not-a-subnet")
        with self.assertRaisesRegex(GatewayError, "Invalid network configuration"):
            config.validate()

    def test_rejects_dhcp_range_containing_gateway(self) -> None:
        config = make_config(
            dhcp_start="192.168.80.1",
            dhcp_end="192.168.80.50",
        )
        with self.assertRaisesRegex(GatewayError, "downstream gateway"):
            config.validate()

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
