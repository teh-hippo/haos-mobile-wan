from __future__ import annotations

import unittest

from rootfs.app.command import RunCommand
from rootfs.app.networkmanager_invariants import (
    main_default_present,
    networkmanager_routes,
)
from rootfs.app.nm_profile import (
    INERT_CREATE_SETTINGS,
    NmProfile,
    inert_create_args,
)
from rootfs.app.nm_profile_specs import (
    USB_ROUTE_TABLE,
    generic_usb_profile_spec,
    usb_profile_spec,
    wifi_profile_spec,
)
from test_support.engine_fixtures import make_config
from test_support.runner import FakeRunner

IPHONE_IFACE = "eth0"
DHCP_OFFER = {"address": "172.20.10.6", "prefix": 28, "gateway": "172.20.10.1"}


def adapter(runner: FakeRunner) -> RunCommand:
    def run(*args: str, check: bool = True, timeout: int = 20):
        return runner.run(list(args), check=check, timeout=timeout)

    return run


def add_command(runner: FakeRunner) -> list[str]:
    for command in runner.commands:
        if command[:3] == ["nmcli", "connection", "add"]:
            return command
    raise AssertionError("no `nmcli connection add` was issued")


def carrier_runner() -> FakeRunner:
    runner = FakeRunner()
    runner.networkmanager.nm_dhcp[IPHONE_IFACE] = dict(DHCP_OFFER)
    runner.networkmanager.nm_wildcard_bind = IPHONE_IFACE
    return runner


class InertCreateArgvTests(unittest.TestCase):
    def _assert_single_inert_pair(self, command: list[str]) -> None:
        for field, value in INERT_CREATE_SETTINGS:
            self.assertEqual(
                command.count(field),
                1,
                f"{field} must appear exactly once in the add argv",
            )
            self.assertEqual(command[command.index(field) + 1], value)

    def test_usb_add_argv_carries_both_inert_settings(self) -> None:
        runner = FakeRunner()
        NmProfile(adapter(runner), usb_profile_spec()).create()
        self._assert_single_inert_pair(add_command(runner))

    def test_wifi_add_argv_carries_both_inert_settings(self) -> None:
        runner = FakeRunner()
        spec = wifi_profile_spec(
            make_config(hotspot_ssid="Phone", hotspot_password="supersecret")
        )
        NmProfile(adapter(runner), spec).create()
        self._assert_single_inert_pair(add_command(runner))

    def test_generic_usb_add_argv_carries_both_inert_settings(self) -> None:
        runner = FakeRunner()
        NmProfile(adapter(runner), generic_usb_profile_spec()).create()
        self._assert_single_inert_pair(add_command(runner))

    def test_inert_args_replace_conflicting_autoconnect_without_duplicates(
        self,
    ) -> None:
        merged = inert_create_args(
            (
                "type",
                "ethernet",
                "connection.autoconnect",
                "yes",
                "connection.autoconnect-retries",
                "3",
            )
        )
        self.assertEqual(merged.count("connection.autoconnect"), 1)
        self.assertEqual(merged.count("connection.autoconnect-retries"), 1)
        self.assertEqual(merged[merged.index("connection.autoconnect") + 1], "no")
        self.assertEqual(
            merged[merged.index("connection.autoconnect-retries") + 1], "0"
        )
        self.assertEqual(merged[:2], ("type", "ethernet"))


class AutoactivationModelTests(unittest.TestCase):
    def test_negative_control_prefix_add_leaks_a_main_default(self) -> None:
        runner = carrier_runner()
        spec = usb_profile_spec()

        runner.run(["nmcli", "connection", "add", *spec.create_args])

        self.assertEqual(runner.networkmanager.nm_active.get(IPHONE_IFACE), spec.uuid)
        self.assertIn(IPHONE_IFACE, runner.routes.interface_addresses)
        self.assertTrue(main_default_present(adapter(runner), IPHONE_IFACE))
        self.assertEqual(runner.networkmanager.nm_routes.get(USB_ROUTE_TABLE, []), [])

    def test_positive_control_inert_create_is_dormant_until_activation(
        self,
    ) -> None:
        runner = carrier_runner()
        profile = NmProfile(adapter(runner), usb_profile_spec())

        profile.create()

        self.assertNotIn(IPHONE_IFACE, runner.networkmanager.nm_active)
        self.assertNotIn(IPHONE_IFACE, runner.routes.interface_addresses)
        self.assertFalse(main_default_present(adapter(runner), IPHONE_IFACE))
        self.assertEqual(runner.networkmanager.nm_routes.get(USB_ROUTE_TABLE, []), [])

        state = profile.activate(IPHONE_IFACE)

        self.assertEqual(state, "active")
        self.assertEqual(
            runner.networkmanager.nm_active.get(IPHONE_IFACE), profile.spec.uuid
        )
        self.assertFalse(main_default_present(adapter(runner), IPHONE_IFACE))
        routes = networkmanager_routes(adapter(runner), USB_ROUTE_TABLE)
        self.assertTrue(
            any(
                route.get("dst") == "default" and route.get("dev") == IPHONE_IFACE
                for route in routes
            ),
            "explicit activation must isolate the default in table 202",
        )


if __name__ == "__main__":
    unittest.main()
