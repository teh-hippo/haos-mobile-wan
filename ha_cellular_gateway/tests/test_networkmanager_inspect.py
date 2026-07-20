"""Inspection, profile-convergence, and route-continuity tests for
NetworkManagerIphone.
"""

from __future__ import annotations

import json
import unittest

from rootfs.app.const import IPHONE_USB
from rootfs.app.errors import GatewayError
from rootfs.app.management import ManagementBaseline
from rootfs.app.networkmanager import (
    MULTIPLE_ADDRESS_MESSAGE,
    NetworkManagerIphone,
)
from rootfs.app.nm_profile import ACTIVATION_COOLDOWN_SECONDS
from rootfs.app.nm_profile_specs import (
    USB_PROFILE_NAME as PROFILE_NAME,
)
from rootfs.app.nm_profile_specs import (
    USB_PROFILE_UUID as PROFILE_UUID,
)
from rootfs.app.nm_profile_specs import (
    USB_ROUTE_TABLE as ROUTE_TABLE,
)
from rootfs.app.nm_profile_specs import usb_profile_spec
from test_support.engine_fixtures import make_config
from test_support.iphone_usb_fixtures import usb_upstream
from test_support.process import Result

EXPECTED_SETTINGS = usb_profile_spec().expected


def converged_profile() -> dict[str, str]:
    return dict(EXPECTED_SETTINGS)


class FakeNetworkManagerCli:
    """Simulate the nmcli and ip surface used by NetworkManagerIphone."""

    def __init__(self) -> None:
        self.profile: dict[str, str] | None = None
        self.active: dict[str, str] = {}
        self.addresses: dict[str, list[str]] = {}
        self.gateways: dict[str, str] = {}
        self.table_routes: list[dict[str, object]] = []
        self.main_default: list[dict[str, object]] = []
        self.rules: list[dict[str, object]] = []
        self.commands: list[list[str]] = []
        self.up_calls = 0
        self.activate_on_up: tuple[str, str] | None = None
        self.clock = 1000.0

    def monotonic(self) -> float:
        return self.clock

    def run(self, *args: str, check: bool = True, timeout: int = 20) -> Result:
        argv = list(args)
        self.commands.append(argv)
        if argv[0] == "nmcli":
            return self._nmcli(argv[1:])
        if argv[0] == "ip":
            return self._ip(argv)
        return Result()

    def _nmcli(self, argv: list[str]) -> Result:
        if argv[:1] == ["--wait"]:
            argv = argv[2:]
        if argv[:1] == ["--show-secrets"]:
            argv = argv[1:]
        if argv[:1] == ["-g"]:
            return self._nmcli_get(argv[1], argv[2], argv[-1])
        if argv[:2] == ["connection", "add"]:
            self.profile = {
                "connection.type": "802-3-ethernet",
                "connection.uuid": PROFILE_UUID,
                "connection.id": PROFILE_NAME,
                "connection.interface-name": "",
            }
            return Result()
        if argv[:2] == ["connection", "modify"]:
            pairs = argv[3:]
            if self.profile is None:
                self.profile = {}
            for index in range(0, len(pairs) - 1, 2):
                self.profile[pairs[index]] = pairs[index + 1]
            return Result()
        if argv[:2] == ["connection", "up"]:
            self.up_calls += 1
            if self.activate_on_up is not None:
                interface, connection = self.activate_on_up
                self.active[interface] = connection
            return Result()
        if argv[:2] == ["connection", "down"]:
            uuid = argv[-1]
            for interface, active_uuid in list(self.active.items()):
                if active_uuid == uuid:
                    del self.active[interface]
            return Result()
        if argv[:2] == ["connection", "delete"]:
            self.profile = None
            return Result()
        return Result()

    def _nmcli_get(self, fields: str, target: str, name: str) -> Result:
        if target == "connection":
            if self.profile is None:
                return Result(returncode=1, stderr="Error: no such connection profile.")
            values = [str(self.profile.get(field, "")) for field in fields.split(",")]
            return Result(stdout="\n".join(values) + "\n")
        field = fields
        if field == "GENERAL.CON-UUID":
            return Result(stdout=self.active.get(name, "") + "\n")
        if field == "IP4.ADDRESS":
            return Result(stdout="\n".join(self.addresses.get(name, [])) + "\n")
        if field == "IP4.GATEWAY":
            gateway = self.gateways.get(name, "")
            return Result(stdout=(gateway + "\n") if gateway else "\n")
        return Result()

    def _ip(self, argv: list[str]) -> Result:
        if argv[:7] == ["ip", "-4", "-j", "route", "show", "table", "main"]:
            return Result(stdout=json.dumps(self.main_default))
        if argv[:7] == ["ip", "-4", "-j", "route", "show", "table", str(ROUTE_TABLE)]:
            return Result(stdout=json.dumps(self.table_routes))
        if argv[:4] == ["ip", "-j", "rule", "show"]:
            return Result(stdout=json.dumps(self.rules))
        return Result(stdout="[]")


def healthy_cli(interface: str = "eth0") -> FakeNetworkManagerCli:
    cli = FakeNetworkManagerCli()
    cli.profile = converged_profile()
    cli.active = {interface: PROFILE_UUID}
    cli.addresses = {interface: ["172.20.10.2/28"]}
    cli.gateways = {interface: "172.20.10.1"}
    cli.table_routes = [
        {"dst": "default", "dev": interface, "gateway": "172.20.10.1"},
        {"dst": "172.20.10.0/28", "dev": interface},
    ]
    return cli


class NetworkManagerInspectTests(unittest.TestCase):
    def _manager(self, cli: FakeNetworkManagerCli) -> NetworkManagerIphone:
        return NetworkManagerIphone(
            make_config(mobile_connection=IPHONE_USB),
            cli.run,
            monotonic=cli.monotonic,
        )

    def test_active_profile_with_valid_lease_resolves_upstream(self) -> None:
        cli = healthy_cli()

        result = self._manager(cli).inspect("eth0")

        self.assertEqual(result.state, "active")
        self.assertTrue(result.safe)
        assert result.upstream is not None
        self.assertEqual(result.upstream.connection, IPHONE_USB)
        self.assertEqual(result.upstream.address, "172.20.10.2/28")
        self.assertEqual(result.upstream.gateway, "172.20.10.1")

    def test_continuity_failure_is_non_throwing(self) -> None:
        cli = healthy_cli()
        manager = self._manager(cli)
        manager.profile.active_uuid = lambda interface: (_ for _ in ()).throw(
            GatewayError("NetworkManager unavailable")
        )

        self.assertFalse(manager.continuity(usb_upstream()))

    def test_no_mutation_while_converged_and_active(self) -> None:
        cli = healthy_cli()

        self._manager(cli).inspect("eth0")

        self.assertEqual(cli.up_calls, 0)
        self.assertEqual(
            [
                c
                for c in cli.commands
                if c[1:3] in (["connection", "modify"], ["connection", "up"])
            ],
            [],
        )

    def test_foreign_profile_fails_closed_without_takeover(self) -> None:
        cli = healthy_cli()
        cli.active = {"eth0": "foreign-profile-uuid"}

        result = self._manager(cli).inspect("eth0")

        self.assertEqual(result.state, "foreign")
        self.assertFalse(result.safe)
        self.assertEqual(cli.up_calls, 0)

    def test_activation_attempt_is_rate_limited(self) -> None:
        cli = healthy_cli()
        cli.active = {}
        manager = self._manager(cli)

        manager.inspect("eth0")
        cli.clock += 5
        manager.inspect("eth0")
        self.assertEqual(cli.up_calls, 1)

        cli.clock += ACTIVATION_COOLDOWN_SECONDS
        manager.inspect("eth0")
        self.assertEqual(cli.up_calls, 2)

    def test_inactive_profile_is_transient_and_safe(self) -> None:
        cli = healthy_cli()
        cli.active = {}

        result = self._manager(cli).inspect("eth0")

        self.assertEqual(result.state, "waiting")
        self.assertTrue(result.safe)
        self.assertIsNone(result.upstream)

    def test_missing_lease_while_active_is_transient(self) -> None:
        cli = healthy_cli()
        cli.addresses = {"eth0": []}
        cli.gateways = {}

        result = self._manager(cli).inspect("eth0")

        self.assertEqual(result.state, "waiting")
        self.assertTrue(result.safe)

    def test_missing_table_routes_while_active_is_transient(self) -> None:
        cli = healthy_cli()
        cli.table_routes = []

        result = self._manager(cli).inspect("eth0")

        self.assertEqual(result.state, "waiting")
        self.assertTrue(result.safe)

    def test_missing_table_default_while_active_is_transient(self) -> None:
        cli = healthy_cli()
        cli.table_routes = [cli.table_routes[1]]

        result = self._manager(cli).inspect("eth0")

        self.assertEqual(result.state, "waiting")
        self.assertTrue(result.safe)

    def test_multiple_table_defaults_fail_closed(self) -> None:
        cli = healthy_cli()
        cli.table_routes.append(dict(cli.table_routes[0]))

        result = self._manager(cli).inspect("eth0")

        self.assertEqual(result.state, "invalid")
        self.assertFalse(result.safe)

    def test_foreign_table_interface_fails_closed(self) -> None:
        cli = healthy_cli()
        cli.table_routes[0]["dev"] = "wg0"

        result = self._manager(cli).inspect("eth0")

        self.assertEqual(result.state, "invalid")
        self.assertFalse(result.safe)

    def test_wrong_table_gateway_fails_closed(self) -> None:
        cli = healthy_cli()
        cli.table_routes[0]["gateway"] = "172.20.10.2"

        result = self._manager(cli).inspect("eth0")

        self.assertEqual(result.state, "invalid")
        self.assertFalse(result.safe)

    def test_unexpected_table_route_fails_closed(self) -> None:
        cli = healthy_cli()
        cli.table_routes.append({"dst": "198.51.100.0/24", "dev": "eth0"})

        result = self._manager(cli).inspect("eth0")

        self.assertEqual(result.state, "invalid")
        self.assertFalse(result.safe)

    def test_duplicate_connected_route_fails_closed(self) -> None:
        cli = healthy_cli()
        cli.table_routes.append(dict(cli.table_routes[1]))

        result = self._manager(cli).inspect("eth0")

        self.assertEqual(result.state, "invalid")
        self.assertFalse(result.safe)

    def test_multiple_addresses_fail_closed(self) -> None:
        cli = healthy_cli()
        cli.addresses = {"eth0": ["172.20.10.2/28", "172.20.10.6/28"]}

        result = self._manager(cli).inspect("eth0")

        self.assertEqual(result.state, "invalid")
        self.assertFalse(result.safe)
        self.assertEqual(result.error, MULTIPLE_ADDRESS_MESSAGE)

    def test_main_default_route_fails_closed(self) -> None:
        cli = healthy_cli()
        cli.main_default = [{"dst": "default", "dev": "eth0", "gateway": "172.20.10.1"}]

        result = self._manager(cli).inspect("eth0")

        self.assertEqual(result.state, "invalid")
        self.assertFalse(result.safe)
        self.assertIn("main table", result.error or "")

    def test_rule_selecting_table_202_fails_closed(self) -> None:
        cli = healthy_cli()
        cli.rules = [{"priority": 100, "table": str(ROUTE_TABLE)}]

        result = self._manager(cli).inspect("eth0")

        self.assertEqual(result.state, "invalid")
        self.assertFalse(result.safe)
        self.assertIn(str(ROUTE_TABLE), result.error or "")

    def test_invalid_lease_overlap_fails_closed(self) -> None:
        cli = healthy_cli()
        cli.addresses = {"eth0": ["192.168.1.20/24"]}
        cli.gateways = {"eth0": "192.168.1.1"}
        cli.table_routes = [
            {"dst": "default", "dev": "eth0", "gateway": "192.168.1.1"},
            {"dst": "192.168.1.0/24", "dev": "eth0"},
        ]

        result = self._manager(cli).inspect(
            "eth0",
            ManagementBaseline("end0", "192.168.1.2/24"),
        )

        self.assertEqual(result.state, "invalid")
        self.assertFalse(result.safe)
        self.assertIn("overlaps the management network", result.error or "")

    def test_missing_connected_route_while_active_is_transient(self) -> None:
        cli = healthy_cli()
        cli.table_routes = [cli.table_routes[0]]

        result = self._manager(cli).inspect("eth0")

        self.assertEqual(result.state, "waiting")
        self.assertTrue(result.safe)

    def test_continuity_fails_when_a_different_profile_is_active(self) -> None:
        cli = healthy_cli()
        cli.active["eth0"] = "other-uuid"

        self.assertFalse(self._manager(cli).continuity(usb_upstream()))

    def test_continuity_fails_when_a_main_default_route_reappears(self) -> None:
        cli = healthy_cli()
        cli.main_default = [{"dst": "default", "dev": "eth0", "gateway": "172.20.10.1"}]

        self.assertFalse(self._manager(cli).continuity(usb_upstream()))

    def test_continuity_fails_when_a_policy_rule_selects_the_usb_table(self) -> None:
        cli = healthy_cli()
        cli.rules = [{"table": str(ROUTE_TABLE)}]

        self.assertFalse(self._manager(cli).continuity(usb_upstream()))

    def test_continuity_fails_when_the_device_address_no_longer_matches(self) -> None:
        cli = healthy_cli()
        cli.addresses["eth0"] = ["172.20.10.9/28"]

        self.assertFalse(self._manager(cli).continuity(usb_upstream()))

    def test_continuity_confirms_a_fully_converged_upstream(self) -> None:
        cli = healthy_cli()

        self.assertTrue(self._manager(cli).continuity(usb_upstream()))

    def test_release_profile_deactivates_and_deletes_the_connection(self) -> None:
        cli = healthy_cli()
        manager = self._manager(cli)

        manager.release_profile()

        self.assertIsNone(cli.profile)
        self.assertNotIn("eth0", cli.active)


if __name__ == "__main__":
    unittest.main()
