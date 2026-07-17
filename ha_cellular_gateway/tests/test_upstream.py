from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from helpers import FakeProcess, FakeRunner, Result, make_config
from rootfs.app.const import IPHONE_USB
from rootfs.app.management import ManagementBaseline
from rootfs.app.networkmanager import (
    ACTIVATION_COOLDOWN_SECONDS,
    EXPECTED_SETTINGS,
    LEASE_OWNER,
    MULTIPLE_ADDRESS_MESSAGE,
    PROFILE_NAME,
    PROFILE_UUID,
    ROUTE_TABLE,
    NetworkManagerIphone,
    NetworkManagerResult,
)
from rootfs.app.upstream_iphone import IPhoneUsbUpstream
from rootfs.app.upstream_models import ResolvedUpstream


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
        if argv[:1] == ["-g"]:
            return self._nmcli_get(argv[1], argv[2], argv[-1])
        if argv[:2] == ["connection", "add"]:
            self.profile = {
                "connection.type": "802-3-ethernet",
                "connection.uuid": PROFILE_UUID,
                "connection.interface-name": "",
            }
            for field in EXPECTED_SETTINGS:
                if field in argv:
                    self.profile[field] = argv[argv.index(field) + 1]
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


class NetworkManagerProfileTests(unittest.TestCase):
    def _manager(self, cli: FakeNetworkManagerCli) -> NetworkManagerIphone:
        return NetworkManagerIphone(
            make_config(mobile_connection=IPHONE_USB),
            cli.run,
            monotonic=cli.monotonic,
        )

    def test_missing_profile_is_created_with_exact_settings(self) -> None:
        cli = FakeNetworkManagerCli()

        self._manager(cli).ensure_profile()

        add = [c for c in cli.commands if c[:3] == ["nmcli", "connection", "add"]]
        modify = [c for c in cli.commands if c[:3] == ["nmcli", "connection", "modify"]]
        self.assertEqual(len(add), 1)
        self.assertEqual(modify, [])
        self.assertIn("match.driver", add[0])
        self.assertIn("ipv4.route-table", add[0])
        assert cli.profile is not None
        for field, expected in EXPECTED_SETTINGS.items():
            self.assertEqual(cli.profile[field], expected)
        self.assertEqual(cli.profile["match.driver"], "ipheth")
        self.assertEqual(cli.profile["ipv4.route-table"], str(ROUTE_TABLE))
        self.assertEqual(cli.profile["ipv4.method"], "auto")
        self.assertEqual(cli.profile["ipv6.method"], "disabled")
        self.assertEqual(cli.profile["connection.interface-name"], "")

    def test_converged_profile_is_not_modified(self) -> None:
        cli = FakeNetworkManagerCli()
        cli.profile = converged_profile()

        self._manager(cli).ensure_profile()

        self.assertEqual(
            [c for c in cli.commands if c[1:3] == ["connection", "add"]],
            [],
        )
        self.assertEqual(
            [c for c in cli.commands if c[1:3] == ["connection", "modify"]],
            [],
        )

    def test_drifted_profile_is_repaired_without_recreating(self) -> None:
        cli = FakeNetworkManagerCli()
        cli.profile = converged_profile()
        cli.profile["ipv4.route-table"] = "254"

        manager = self._manager(cli)
        manager.ensure_profile()

        self.assertEqual(
            [c for c in cli.commands if c[1:3] == ["connection", "add"]],
            [],
        )
        self.assertEqual(cli.profile["ipv4.route-table"], str(ROUTE_TABLE))
        cli.profile["ipv4.route-table"] = "254"
        manager.ensure_profile()
        modify = [c for c in cli.commands if c[1:3] == ["connection", "modify"]]
        self.assertEqual(len(modify), 1)

    def test_drifted_active_profile_is_reactivated_once(self) -> None:
        cli = healthy_cli()
        cli.profile = converged_profile()
        cli.profile["ipv4.route-table"] = "254"
        cli.activate_on_up = ("eth0", PROFILE_UUID)
        manager = self._manager(cli)

        manager.ensure_profile()
        result = manager.inspect("eth0")

        self.assertEqual(result.state, "active")
        self.assertEqual(cli.up_calls, 1)


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

    def test_no_mutation_while_converged_and_active(self) -> None:
        cli = healthy_cli()

        self._manager(cli).inspect("eth0")

        self.assertEqual(cli.up_calls, 0)
        self.assertEqual(
            [c for c in cli.commands if c[1:3] in (["connection", "modify"], ["connection", "up"])],
            [],
        )

    def test_foreign_profile_is_brought_up_once_then_fails_closed(self) -> None:
        cli = healthy_cli()
        cli.active = {"eth0": "foreign-profile-uuid"}

        result = self._manager(cli).inspect("eth0")

        self.assertEqual(result.state, "foreign")
        self.assertFalse(result.safe)
        self.assertEqual(cli.up_calls, 1)
        self.assertIn(
            [
                "nmcli", "--wait", "8", "connection", "up",
                "uuid", PROFILE_UUID, "ifname", "eth0",
            ],
            cli.commands,
        )

    def test_foreign_profile_takeover_that_succeeds_is_active(self) -> None:
        cli = healthy_cli()
        cli.active = {"eth0": "foreign-profile-uuid"}
        cli.activate_on_up = ("eth0", PROFILE_UUID)

        result = self._manager(cli).inspect("eth0")

        self.assertEqual(result.state, "active")
        self.assertEqual(cli.up_calls, 1)

    def test_activation_attempt_is_rate_limited(self) -> None:
        cli = healthy_cli()
        cli.active = {"eth0": "foreign-profile-uuid"}
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


class FakeNetworkManager:
    def __init__(
        self,
        results: list[NetworkManagerResult] | None = None,
        *,
        profile_error: Exception | None = None,
    ) -> None:
        self.results = list(results or [])
        self.profile_error = profile_error
        self.profile_calls = 0
        self.inspect_calls: list[str] = []
        self.default = NetworkManagerResult(None, "waiting", "waiting", True)

    def ensure_profile(self) -> None:
        self.profile_calls += 1
        if self.profile_error is not None:
            raise self.profile_error

    def inspect(
        self,
        interface: str,
        management: object = None,
    ) -> NetworkManagerResult:
        self.inspect_calls.append(interface)
        if self.results:
            return self.results.pop(0)
        return self.default


def usb_upstream(interface: str = "eth0") -> ResolvedUpstream:
    return ResolvedUpstream(
        connection=IPHONE_USB,
        interface=interface,
        address="172.20.10.2/28",
        gateway="172.20.10.1",
    )


class IPhoneUsbUpstreamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.run_dir = self.root / "run"
        self.usb_root = self.root / "dev" / "bus" / "usb"
        self.sys_net_root = self.root / "sys" / "class" / "net"
        self.sys_usb_root = self.root / "sys" / "bus" / "usb" / "devices"
        self.driver_root = self.root / "drivers"
        for path in (
            self.usb_root,
            self.sys_net_root,
            self.sys_usb_root,
            self.driver_root,
        ):
            path.mkdir(parents=True)
        self.clock = [1000.0]

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _tick(self) -> float:
        return self.clock[0]

    def _manager(
        self,
        runner: FakeRunner,
        network_manager: FakeNetworkManager,
        *,
        popen=None,
    ) -> IPhoneUsbUpstream:
        return IPhoneUsbUpstream(
            make_config(mobile_connection=IPHONE_USB),
            lambda *args, **kwargs: runner.run(list(args), **kwargs),
            run_dir=self.run_dir,
            lockdown_dir=self.root / "lockdown",
            usb_root=self.usb_root,
            sys_net_root=self.sys_net_root,
            sys_usb_root=self.sys_usb_root,
            which=lambda command: f"/usr/bin/{command}",
            popen=popen or (lambda *args, **kwargs: FakeProcess()),
            network_manager=network_manager,
            monotonic=self._tick,
        )

    def _add_ipheth_interface(self, name: str = "eth0") -> None:
        target = self.driver_root / "ipheth"
        target.mkdir(exist_ok=True)
        interface = self.sys_net_root / name / "device"
        interface.mkdir(parents=True)
        (interface / "driver").symlink_to(target)

    def _add_apple_usb_device(self, name: str = "1-1") -> None:
        device = self.sys_usb_root / name
        device.mkdir(parents=True)
        (device / "idVendor").write_text("05ac\n", encoding="utf-8")

    def _paired_runner(self) -> FakeRunner:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        runner.idevice_paired_udids = ["iphone-udid"]
        runner.idevice_validate_result.returncode = 0
        return runner

    def test_reports_networkmanager_lease_owner(self) -> None:
        manager = self._manager(FakeRunner(), FakeNetworkManager())
        self.assertEqual(
            manager.runtime_status()["upstream_lease_owner"],
            None,
        )

    def test_missing_nmcli_is_a_capability_error(self) -> None:
        runner = self._paired_runner()
        manager = IPhoneUsbUpstream(
            make_config(mobile_connection=IPHONE_USB),
            lambda *args, **kwargs: runner.run(list(args), **kwargs),
            run_dir=self.run_dir,
            lockdown_dir=self.root / "lockdown",
            usb_root=self.usb_root,
            sys_net_root=self.sys_net_root,
            sys_usb_root=self.sys_usb_root,
            which=lambda command: None if command == "nmcli" else f"/usr/bin/{command}",
            popen=lambda *args, **kwargs: FakeProcess(),
            network_manager=FakeNetworkManager(),
        )

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertIn("Required command is unavailable: nmcli", errors)

    def test_phone_absence_does_not_prepare_profile_or_start_helper(self) -> None:
        processes: list[FakeProcess] = []
        network_manager = FakeNetworkManager()
        manager = self._manager(
            FakeRunner(),
            network_manager,
            popen=lambda *args, **kwargs: processes.append(FakeProcess())
            or processes[-1],
        )

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(network_manager.profile_calls, 0)
        self.assertEqual(network_manager.inspect_calls, [])
        self.assertEqual(processes, [])
        self.assertEqual(manager.pairing_state, "waiting_for_device")

    def test_profile_setup_failure_allows_fallback(self) -> None:
        runner = self._paired_runner()
        from rootfs.app.errors import GatewayError

        self._add_apple_usb_device()
        network_manager = FakeNetworkManager(profile_error=GatewayError("nm down"))
        manager = self._manager(runner, network_manager)

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(manager.pairing_state, "profile_failed")
        self.assertTrue(manager.fallback_allowed())

    def test_active_profile_resolves_upstream(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        network_manager = FakeNetworkManager(
            [NetworkManagerResult(usb_upstream(), "active", None, True)]
        )
        manager = self._manager(runner, network_manager)

        upstream, errors = manager.resolve()

        self.assertEqual(errors, [])
        assert upstream is not None
        self.assertEqual(upstream.interface, "eth0")
        self.assertEqual(manager.pairing_state, "paired")
        self.assertEqual(network_manager.inspect_calls, ["eth0"])
        self.assertEqual(
            manager.runtime_status()["upstream_lease_owner"],
            LEASE_OWNER,
        )

    def test_pairing_is_still_required(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        self._add_apple_usb_device()
        manager = self._manager(runner, FakeNetworkManager())

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertIn("tap Trust", errors[0])
        self.assertEqual(manager.pairing_state, "waiting_for_trust")

    def test_pairing_prompt_is_rate_limited(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        self._add_apple_usb_device()
        manager = self._manager(runner, FakeNetworkManager())

        from unittest.mock import patch

        with patch(
            "rootfs.app.upstream_iphone_runtime.time.monotonic",
            side_effect=[100.0, 105.0, 161.0],
        ):
            manager.resolve()
            manager.resolve()
            pair_commands = [c for c in runner.commands if c[-1:] == ["pair"]]
            self.assertEqual(len(pair_commands), 1)

            manager.resolve()
            pair_commands = [c for c in runner.commands if c[-1:] == ["pair"]]
            self.assertEqual(len(pair_commands), 2)

    def test_multiple_devices_block_fallback(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["one", "two"]
        self._add_apple_usb_device()
        manager = self._manager(runner, FakeNetworkManager())

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(manager.pairing_state, "multiple_devices")
        self.assertFalse(manager.fallback_allowed())

    def test_multiple_ipheth_interfaces_block_fallback(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        self._add_ipheth_interface("eth1")
        manager = self._manager(runner, FakeNetworkManager())

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(manager.pairing_state, "multiple_devices")
        self.assertFalse(manager.fallback_allowed())

    def test_profile_conflict_blocks_fallback(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        network_manager = FakeNetworkManager(
            [NetworkManagerResult(None, "foreign", "foreign profile", False)]
        )
        manager = self._manager(runner, network_manager)

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(manager.pairing_state, "profile_conflict")
        self.assertFalse(manager.fallback_allowed())

    def test_invalid_lease_blocks_fallback(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        network_manager = FakeNetworkManager(
            [NetworkManagerResult(None, "invalid", "bad lease", False)]
        )
        manager = self._manager(runner, network_manager)

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(manager.pairing_state, "invalid_lease")
        self.assertFalse(manager.fallback_allowed())

    def test_waiting_profile_allows_fallback(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        network_manager = FakeNetworkManager(
            [NetworkManagerResult(None, "waiting", "waiting", True)]
        )
        manager = self._manager(runner, network_manager)

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(manager.pairing_state, "waiting_for_profile")
        self.assertTrue(manager.fallback_allowed())

    def test_missing_lease_within_grace_keeps_last_upstream(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        network_manager = FakeNetworkManager(
            [
                NetworkManagerResult(usb_upstream(), "active", None, True),
                NetworkManagerResult(None, "waiting", "renewing", True),
                NetworkManagerResult(None, "waiting", "renewing", True),
            ]
        )
        manager = self._manager(runner, network_manager)

        first, _ = manager.resolve()
        assert first is not None
        self.clock[0] += 5
        grace, errors = manager.resolve()

        self.assertEqual(errors, [])
        self.assertEqual(grace, usb_upstream())
        self.assertEqual(manager.pairing_state, "paired")

        self.clock[0] += IPhoneUsbUpstream.LEASE_GRACE_SECONDS
        expired, errors = manager.resolve()

        self.assertIsNone(expired)
        self.assertEqual(manager.pairing_state, "waiting_for_profile")

    def test_cleanup_does_not_mutate_networkmanager_state(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        network_manager = FakeNetworkManager(
            [NetworkManagerResult(usb_upstream(), "active", None, True)]
        )
        manager = self._manager(runner, network_manager)
        manager.resolve()
        runner.commands.clear()

        manager.cleanup()

        self.assertFalse(
            any(
                command[:4] == ["ip", "-4", "address", "del"]
                or command[:1] == ["nmcli"]
                for command in runner.commands
            )
        )
        self.assertEqual(network_manager.profile_calls, 1)

    def test_driver_inactive_message_when_no_interface(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        manager = self._manager(runner, FakeNetworkManager())
        manager.runtime.ipheth_driver_active = lambda: False

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(manager.pairing_state, "waiting_for_interface")
        self.assertIn("ipheth driver is not active", errors[0])

    def test_usbmuxd_startup_failure_surfaces_output(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        self._add_ipheth_interface()
        self._add_apple_usb_device()

        def popen(*args, **kwargs):
            kwargs["stdout"].write("socket bind failed\n")
            kwargs["stdout"].flush()
            kwargs["stderr"].write("permission denied\n")
            kwargs["stderr"].flush()
            return FakeProcess(running=False, returncode=1)

        upstream, errors = self._manager(
            runner,
            FakeNetworkManager(),
            popen=popen,
        ).resolve()

        self.assertIsNone(upstream)
        self.assertEqual(
            errors,
            ["usbmuxd failed to start: socket bind failed; permission denied"],
        )


if __name__ == "__main__":
    unittest.main()
