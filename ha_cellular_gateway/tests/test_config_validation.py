from __future__ import annotations

import unittest

from rootfs.app.errors import GatewayError
from test_support.engine_fixtures import make_config


class InterfaceAndCredentialFormatTests(unittest.TestCase):
    def test_wifi_mode_requires_a_non_empty_upstream_interface(self) -> None:
        config = make_config(upstream_interface="")
        with self.assertRaisesRegex(GatewayError, "interface names must not be empty"):
            config.validate()

    def test_rejects_an_ssid_with_an_unpaired_surrogate(self) -> None:
        config = make_config(hotspot_ssid="\ud800", hotspot_password="validpass")
        with self.assertRaisesRegex(GatewayError, "valid UTF-8"):
            config.validate()


class DownstreamAddressFormatTests(unittest.TestCase):
    def test_rejects_an_unparsable_downstream_address(self) -> None:
        config = make_config(downstream_address="not-an-address")
        with self.assertRaisesRegex(GatewayError, "Invalid network configuration"):
            config.validate()

    def test_rejects_an_ipv6_downstream_address(self) -> None:
        config = make_config(downstream_address="fd00::1/64")
        with self.assertRaisesRegex(GatewayError, "Only IPv4 gateway mode"):
            config.validate()


class UpstreamAddressFormatTests(unittest.TestCase):
    def test_rejects_an_unparsable_upstream_address(self) -> None:
        config = make_config(upstream_address="not-an-address")
        with self.assertRaisesRegex(GatewayError, "Invalid network configuration"):
            config.validate()

    def test_rejects_an_ipv6_upstream_address(self) -> None:
        config = make_config(upstream_address="fd00::1/64")
        with self.assertRaisesRegex(GatewayError, "Only IPv4 gateway mode"):
            config.validate()

    def test_rejects_an_unparsable_upstream_gateway(self) -> None:
        config = make_config(upstream_gateway="not-an-address")
        with self.assertRaisesRegex(GatewayError, "Invalid network configuration"):
            config.validate()

    def test_rejects_an_ipv6_upstream_gateway(self) -> None:
        config = make_config(upstream_gateway="fd00::1")
        with self.assertRaisesRegex(GatewayError, "Only IPv4 gateway mode"):
            config.validate()

    def test_rejects_upstream_network_or_broadcast_address(self) -> None:
        for address in ("172.20.10.0/28", "172.20.10.15/28"):
            with self.subTest(address=address):
                config = make_config(upstream_address=address)
                with self.assertRaisesRegex(GatewayError, "not a usable host address"):
                    config.validate()

    def test_rejects_a_gateway_outside_the_upstream_subnet(self) -> None:
        config = make_config(upstream_gateway="172.20.11.1")
        with self.assertRaisesRegex(GatewayError, "outside the upstream subnet"):
            config.validate()

    def test_rejects_a_gateway_matching_an_upstream_peer_address(self) -> None:
        for gateway in ("172.20.10.4", "172.20.10.0", "172.20.10.15"):
            with self.subTest(gateway=gateway):
                config = make_config(upstream_gateway=gateway)
                with self.assertRaisesRegex(GatewayError, "not a usable peer address"):
                    config.validate()


if __name__ == "__main__":
    unittest.main()
