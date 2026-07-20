"""Gate-error, control-error, and route-continuity tests for
NetworkManagerWifi's inspection state machine (the branches not already
exercised through WifiCustodianTests in test_wifi_custody.py).
"""

from __future__ import annotations

import unittest

from rootfs.app.errors import GatewayError
from rootfs.app.networkmanager_wifi import (
    WIFI_DEFAULT_MESSAGE,
    WIFI_NOT_ASSOCIATED,
    WIFI_ROUTE_MESSAGE,
    WIFI_RULE_MESSAGE,
    NetworkManagerWifi,
)
from rootfs.app.nm_profile_specs import WIFI_ROUTE_TABLE
from rootfs.app.wifi_custody import DISPLACE_FAILED
from test_support.engine_fixtures import make_config
from test_support.metadata import FakeWifiProfileMetadata
from test_support.runner import FakeRunner


class NetworkManagerWifiTests(unittest.TestCase):
    def _controller(self, runner: FakeRunner) -> NetworkManagerWifi:
        config = make_config(hotspot_ssid="Phone", hotspot_password="supersecret")
        controller = NetworkManagerWifi(
            config,
            lambda *args, **kwargs: runner.run(list(args), **kwargs),
            monotonic=lambda: 1000.0,
            metadata=FakeWifiProfileMetadata(),
        )
        controller.set_persist(lambda: None)
        return controller

    def _active_controller(self, runner: FakeRunner) -> NetworkManagerWifi:
        runner.networkmanager.nm_wifi_cache["wlan0"] = {"Phone"}
        controller = self._controller(runner)
        controller.claim("end0")
        result = controller.inspect()
        self.assertEqual(result.state, "active")
        return controller

    def test_inspect_waits_before_any_claim(self) -> None:
        controller = self._controller(FakeRunner())

        result = controller.inspect()

        self.assertEqual(result.state, "waiting")
        self.assertTrue(result.safe)
        self.assertEqual(result.error, WIFI_NOT_ASSOCIATED)

    def test_claim_reports_apply_gate_errors_and_blocks(self) -> None:
        runner = FakeRunner()
        runner.routes.add_main_default_route(
            {"dst": "default", "dev": "wlan0", "gateway": "172.20.10.1"}
        )
        controller = self._controller(runner)

        errors = controller.claim("end0")

        self.assertEqual(errors, [DISPLACE_FAILED])
        self.assertFalse(controller.held)
        self.assertEqual(controller.blocker, DISPLACE_FAILED)
        self.assertEqual(controller.phase(), "blocked")

    def test_inspect_recovers_from_a_control_error(self) -> None:
        runner = FakeRunner()
        controller = self._controller(runner)
        controller.claim("end0")

        def raise_control_error(interface: str) -> str:
            raise GatewayError("NetworkManager unavailable")

        controller.profile.active_uuid = raise_control_error  # type: ignore[method-assign]

        result = controller.inspect()

        self.assertEqual(result.state, "waiting")
        self.assertTrue(result.safe)
        self.assertIn("inspection is unavailable", result.error or "")

    def test_verify_active_fails_when_a_stray_main_default_route_appears(
        self,
    ) -> None:
        runner = FakeRunner()
        controller = self._active_controller(runner)
        runner.routes.add_main_default_route(
            {"dst": "default", "dev": "wlan0", "gateway": "172.20.10.1"}
        )

        result = controller.inspect()

        self.assertEqual(result.state, "invalid")
        self.assertFalse(result.safe)
        self.assertEqual(result.error, WIFI_DEFAULT_MESSAGE)

    def test_verify_active_fails_when_a_policy_rule_selects_the_wifi_table(
        self,
    ) -> None:
        runner = FakeRunner()
        controller = self._active_controller(runner)
        runner.routes.policy_rules.append({"table": str(WIFI_ROUTE_TABLE)})

        result = controller.inspect()

        self.assertEqual(result.state, "invalid")
        self.assertFalse(result.safe)
        self.assertEqual(result.error, WIFI_RULE_MESSAGE)

    def test_verify_active_waits_when_the_configured_address_disappears(
        self,
    ) -> None:
        runner = FakeRunner()
        controller = self._active_controller(runner)
        runner.routes.interface_addresses.pop("wlan0", None)

        result = controller.inspect()

        self.assertEqual(result.state, "waiting")
        self.assertTrue(result.safe)
        self.assertEqual(result.error, WIFI_NOT_ASSOCIATED)

    def test_verify_active_fails_when_the_wifi_table_has_unexpected_routes(
        self,
    ) -> None:
        runner = FakeRunner()
        controller = self._active_controller(runner)
        runner.networkmanager.nm_routes[WIFI_ROUTE_TABLE] = [
            {
                "dst": "default",
                "dev": "wlan0",
                "gateway": "172.20.10.1",
                "prefsrc": "172.20.10.4",
            },
            {"dst": "10.0.0.0/24", "dev": "wlan0", "prefsrc": "172.20.10.4"},
        ]

        result = controller.inspect()

        self.assertEqual(result.state, "invalid")
        self.assertFalse(result.safe)
        self.assertEqual(result.error, WIFI_ROUTE_MESSAGE)

    def test_verify_active_waits_when_the_wifi_table_route_is_incomplete(
        self,
    ) -> None:
        runner = FakeRunner()
        controller = self._active_controller(runner)
        runner.networkmanager.nm_routes[WIFI_ROUTE_TABLE] = [
            {
                "dst": "default",
                "dev": "wlan0",
                "gateway": "172.20.10.1",
                "prefsrc": "172.20.10.4",
            }
        ]

        result = controller.inspect()

        self.assertEqual(result.state, "waiting")
        self.assertTrue(result.safe)
        self.assertEqual(result.error, WIFI_NOT_ASSOCIATED)


if __name__ == "__main__":
    unittest.main()
