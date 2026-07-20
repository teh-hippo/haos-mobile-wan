from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rootfs.app.const import IPHONE_USB, IPHONE_USB_WIFI_FALLBACK
from rootfs.app.gateway import GatewayEngine
from rootfs.app.management import ManagementBaseline
from rootfs.app.nm_profile_specs import (
    USB_PROFILE_UUID,
    USB_ROUTE_TABLE,
    WIFI_PROFILE_UUID,
)
from test_support.engine_fixtures import build_engine, make_config, sysctl_values
from test_support.process import FakeProcess
from test_support.runner import FakeRunner

IPHONE_IFACE = "eth0"
DHCP_OFFER = {"address": "172.20.10.6", "prefix": 28, "gateway": "172.20.10.1"}


def _safety_errors(*args, upstream=None, upstream_errors=None, **kwargs):
    """Keep management and NetworkManager checks real; neutralise the rest."""
    if upstream is None:
        return list(upstream_errors or [])
    return []


def _stub_iphone_runtime(engine: GatewayEngine) -> None:
    """Present a paired, carrier-up iPhone so the real NM lease path runs."""
    runtime = engine.upstream.runtime
    runtime.capability_errors = lambda: []
    runtime.apple_usb_present = lambda: True
    runtime.ensure_usbmuxd = lambda: None
    runtime.connected_udids = lambda: ["udid-live-1"]
    runtime.validate_pairing = lambda udid: True
    runtime.ipheth_interfaces = lambda: [IPHONE_IFACE]
    runtime.interface_carrier = lambda interface: True


def _connection_verbs(commands: list[list[str]], verb: str, uuid: str) -> int:
    total = 0
    for command in commands:
        for index in range(len(command) - 3):
            if (
                command[index : index + 3] == ["connection", verb, "uuid"]
                and command[index + 3] == uuid
            ):
                total += 1
                break
    return total


def _adds(commands: list[list[str]], uuid: str) -> int:
    return sum(
        1
        for command in commands
        if command[:3] == ["nmcli", "connection", "add"] and uuid in command
    )


class UsbRestartRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.state_path = Path(self.directory.name) / "state.json"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _engine(self, mode: str, runner: FakeRunner) -> GatewayEngine:
        values = sysctl_values()
        engine = build_engine(
            make_config(
                mobile_connection=mode,
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            runner=runner,
            read_text=lambda path: values[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"
        engine.safety.errors = _safety_errors
        engine.lifecycle_state.management_interface = "end0"
        engine.management = ManagementBaseline("end0", "192.168.1.2/24")
        engine.dhcp.start = lambda downstream: setattr(
            engine.dhcp, "process", FakeProcess()
        )
        _stub_iphone_runtime(engine)
        return engine

    def _iphone_main_defaults(self, runner: FakeRunner) -> list:
        return [
            route
            for route in runner.routes.main_default_routes
            if route.get("dev") == IPHONE_IFACE
        ]

    def _table_202_ready(self, runner: FakeRunner) -> bool:
        return any(
            route.get("dst") == "default"
            and route.get("dev") == IPHONE_IFACE
            and route.get("gateway") == DHCP_OFFER["gateway"]
            for route in runner.networkmanager.nm_routes.get(USB_ROUTE_TABLE, [])
        )

    def test_options_restart_recreates_usb_once_without_oscillation(
        self,
    ) -> None:
        runner = FakeRunner()
        runner.networkmanager.nm_dhcp[IPHONE_IFACE] = dict(DHCP_OFFER)
        runner.networkmanager.nm_wildcard_bind = IPHONE_IFACE
        runner.networkmanager.nm_wifi_cache["wlan0"] = {"Phone"}

        # A live USB-only gateway: the inert profile is created, explicitly
        # activated, and takes its DHCP lease isolated in table 202.
        live = self._engine(IPHONE_USB, runner)
        live.reconcile()
        self.assertEqual(live.selection_state.active_connection, IPHONE_USB)
        self.assertEqual(
            runner.networkmanager.nm_active.get(IPHONE_IFACE), USB_PROFILE_UUID
        )
        self.assertTrue(self._table_202_ready(runner))

        # Changing options restarts the add-on: the old engine stops gracefully
        # and deletes/deactivates its USB profile and lease. The physical ipheth
        # device, carrier and DHCP peer stay available across the restart.
        live.stop()
        self.assertNotIn(USB_PROFILE_UUID, runner.networkmanager.nm_profiles)
        self.assertNotIn(IPHONE_IFACE, runner.networkmanager.nm_active)
        self.assertNotIn(IPHONE_IFACE, runner.routes.interface_addresses)
        self.assertEqual(runner.networkmanager.nm_routes.get(USB_ROUTE_TABLE, []), [])
        self.assertEqual(self._iphone_main_defaults(runner), [])
        self.assertIn(IPHONE_IFACE, runner.networkmanager.nm_dhcp)
        self.assertEqual(runner.networkmanager.nm_wildcard_bind, IPHONE_IFACE)

        # A fresh engine starts in USB-preferred Wi-Fi fallback.
        restarted = self._engine(IPHONE_USB_WIFI_FALLBACK, runner)
        mark = len(runner.commands)

        for _ in range(3):
            restarted.reconcile()
            self.assertIsNotNone(restarted.management)
            assert restarted.management is not None
            self.assertEqual(restarted.management.interface, "end0")

        commands = runner.commands[mark:]
        # The restarted engine recreates and activates the USB profile exactly
        # once, then issues no further add/delete/up across reconciles.
        self.assertEqual(_adds(commands, USB_PROFILE_UUID), 1)
        self.assertEqual(_connection_verbs(commands, "up", USB_PROFILE_UUID), 1)
        self.assertEqual(_connection_verbs(commands, "delete", USB_PROFILE_UUID), 0)
        self.assertEqual(_connection_verbs(commands, "down", USB_PROFILE_UUID), 0)

        # Kernel truth: main clean, lease isolated in table 202, USB preferred.
        self.assertEqual(self._iphone_main_defaults(runner), [])
        self.assertTrue(self._table_202_ready(runner))
        self.assertEqual(restarted.selection_state.active_connection, IPHONE_USB)
        self.assertEqual(
            runner.networkmanager.nm_active.get(IPHONE_IFACE), USB_PROFILE_UUID
        )

        # Wi-Fi ownership prepares exactly once as stable warm standby.
        self.assertIn(WIFI_PROFILE_UUID, runner.networkmanager.nm_profiles)
        self.assertEqual(_adds(commands, WIFI_PROFILE_UUID), 1)
        self.assertEqual(_connection_verbs(commands, "delete", WIFI_PROFILE_UUID), 0)


if __name__ == "__main__":
    unittest.main()
