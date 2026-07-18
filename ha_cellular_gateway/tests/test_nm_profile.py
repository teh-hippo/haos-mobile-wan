from __future__ import annotations

import json
import unittest

from helpers import Result, make_config
from rootfs.app.management import ManagementBaseline
from rootfs.app.nm_inventory import NmInventory
from rootfs.app.nm_preflight import (
    MANAGEMENT_REQUIRED,
    USB_FOREIGN_PROFILE,
    WIFI_FOREIGN_PROFILE,
    inspect_nm_ownership,
)
from rootfs.app.networkmanager_wifi import (
    WIFI_FOREIGN_MESSAGE,
    NetworkManagerWifi,
)
from rootfs.app.nm_profile import NmProfile
from rootfs.app.nm_profile_specs import (
    WIFI_PROFILE_UUID,
    WIFI_ROUTE_TABLE,
    usb_profile_spec,
    wifi_profile_spec,
)


class FakeNmcli:
    def __init__(self) -> None:
        self.profiles: dict[str, dict[str, str]] = {}
        self.active: dict[str, str] = {}
        self.commands: list[list[str]] = []
        self.clock = 100.0
        self.activate_on_up: dict[str, str] = {}
        self.addresses: dict[str, list[str]] = {}
        self.table_routes: dict[int, list[dict[str, object]]] = {}
        self.main_default: list[dict[str, object]] = []
        self.rules: list[dict[str, object]] = []

    def monotonic(self) -> float:
        return self.clock

    def run(self, *args: str, check: bool = True, timeout: int = 20) -> Result:
        argv = list(args)
        self.commands.append(argv)
        if argv[0] == "ip":
            if argv[:7] == [
                "ip",
                "-4",
                "-j",
                "route",
                "show",
                "table",
                "main",
            ]:
                return Result(stdout=json.dumps(self.main_default))
            if argv[:6] == ["ip", "-4", "-j", "route", "show", "table"]:
                return Result(
                    stdout=json.dumps(
                        self.table_routes.get(int(argv[6]), [])
                    )
                )
            if argv[:4] == ["ip", "-j", "rule", "show"]:
                return Result(stdout=json.dumps(self.rules))
            return Result(stdout="[]")
        if argv[0] != "nmcli":
            return Result()
        command = argv[1:]
        if command[:4] == ["-t", "--separator", "|", "-f"]:
            lines = [
                "|".join(
                    (
                        uuid,
                        profile.get("connection.type", ""),
                        profile.get("connection.id", ""),
                    )
                )
                for uuid, profile in self.profiles.items()
            ]
            return Result(stdout="\n".join(lines) + ("\n" if lines else ""))
        if command[:2] == ["--show-secrets", "-g"]:
            fields = command[2].split(",")
            uuid = command[-1]
            profile = self.profiles.get(uuid)
            if profile is None:
                return Result(returncode=10)
            return Result(
                stdout="\n".join(profile.get(field, "") for field in fields) + "\n"
            )
        if command[:1] == ["-g"] and command[2:4] == ["connection", "show"]:
            fields = command[1].split(",")
            profile = self.profiles.get(command[-1])
            if profile is None:
                return Result(returncode=10)
            return Result(
                stdout="\n".join(profile.get(field, "") for field in fields) + "\n"
            )
        if command[:2] == ["connection", "add"]:
            uuid = command[command.index("connection.uuid") + 1]
            name = command[command.index("con-name") + 1]
            connection_type = command[command.index("type") + 1]
            self.profiles[uuid] = {
                "connection.uuid": uuid,
                "connection.id": name,
                "connection.type": (
                    "802-3-ethernet"
                    if connection_type == "ethernet"
                    else "802-11-wireless"
                ),
            }
            return Result()
        if command[:2] == ["connection", "modify"]:
            uuid = command[2]
            profile = self.profiles[uuid]
            pairs = command[3:]
            for index in range(0, len(pairs), 2):
                profile[pairs[index]] = pairs[index + 1]
            return Result()
        if command[:3] == ["connection", "up", "uuid"]:
            uuid = command[3]
            interface = self.activate_on_up.get(uuid)
            if interface:
                self.active[interface] = uuid
            return Result()
        if command[:3] == ["connection", "down", "uuid"]:
            uuid = command[3]
            for interface, active_uuid in list(self.active.items()):
                if active_uuid == uuid:
                    del self.active[interface]
            return Result()
        if command[:3] == ["connection", "delete", "uuid"]:
            self.profiles.pop(command[3], None)
            return Result()
        if command[:3] == ["-g", "GENERAL.CON-UUID", "device"]:
            interface = command[-1]
            return Result(stdout=self.active.get(interface, "") + "\n")
        if command[:3] == ["-g", "IP4.ADDRESS", "device"]:
            interface = command[-1]
            return Result(
                stdout="\n".join(self.addresses.get(interface, [])) + "\n"
            )
        return Result()


class NmProfileTests(unittest.TestCase):
    def _profile(self, cli: FakeNmcli, *, wifi: bool = False) -> NmProfile:
        spec = (
            wifi_profile_spec(
                make_config(
                    hotspot_ssid="Phone",
                    hotspot_password="supersecret",
                )
            )
            if wifi
            else usb_profile_spec()
        )
        return NmProfile(cli.run, spec, monotonic=cli.monotonic)

    def test_create_produces_exact_profile(self) -> None:
        cli = FakeNmcli()
        profile = self._profile(cli)

        profile.create()

        self.assertEqual(profile.inspect().state, "exact")
        self.assertEqual(
            cli.profiles[profile.spec.uuid]["connection.autoconnect"],
            "no",
        )

    def test_drift_is_reported_without_mutation(self) -> None:
        cli = FakeNmcli()
        profile = self._profile(cli)
        profile.create()
        cli.profiles[profile.spec.uuid]["ipv4.route-table"] = "254"
        before = len(cli.commands)

        inspection = profile.inspect()

        self.assertEqual(inspection.state, "drifted")
        self.assertIn("ipv4.route-table", inspection.drifted_fields)
        self.assertEqual(len(cli.commands), before + 1)

    def test_foreign_active_profile_is_not_challenged(self) -> None:
        cli = FakeNmcli()
        profile = self._profile(cli)
        profile.create()
        cli.active["eth0"] = "foreign"
        before = len(cli.commands)

        state = profile.activate("eth0")

        self.assertEqual(state, "foreign")
        self.assertFalse(
            any(
                command[3:6] == ["connection", "up", "uuid"]
                for command in cli.commands[before:]
            )
        )

    def test_activation_cooldown_is_per_interface(self) -> None:
        cli = FakeNmcli()
        profile = self._profile(cli)
        profile.create()

        profile.activate("eth0")
        profile.activate("eth1")

        up_commands = [
            command
            for command in cli.commands
            if command[3:6] == ["connection", "up", "uuid"]
        ]
        self.assertEqual(len(up_commands), 2)

    def test_wifi_profile_is_bound_and_secret_is_verified(self) -> None:
        cli = FakeNmcli()
        profile = self._profile(cli, wifi=True)

        profile.create()

        self.assertEqual(profile.inspect().state, "exact")
        settings = cli.profiles[profile.spec.uuid]
        self.assertEqual(settings["connection.interface-name"], "wlan0")
        self.assertEqual(
            settings["802-11-wireless-security.psk"],
            "supersecret",
        )

    def test_deactivate_and_delete_remove_only_app_profile(self) -> None:
        cli = FakeNmcli()
        profile = self._profile(cli)
        profile.create()
        cli.active["eth0"] = profile.spec.uuid
        cli.profiles["foreign"] = {"connection.uuid": "foreign"}

        profile.deactivate()
        profile.delete()

        self.assertEqual(cli.active, {})
        self.assertNotIn(profile.spec.uuid, cli.profiles)
        self.assertIn("foreign", cli.profiles)

    def test_wifi_controller_returns_active_isolated_upstream(self) -> None:
        cli = FakeNmcli()
        config = make_config(
            hotspot_ssid="Phone",
            hotspot_password="supersecret",
        )
        manager = NetworkManagerWifi(
            config,
            cli.run,
            monotonic=cli.monotonic,
        )
        manager.profile.create()
        cli.active["wlan0"] = WIFI_PROFILE_UUID
        cli.addresses["wlan0"] = [config.upstream_address]
        address = config.upstream_ip
        network = config.upstream_address
        from ipaddress import ip_interface

        subnet = str(ip_interface(network).network)
        cli.table_routes[WIFI_ROUTE_TABLE] = [
            {
                "dst": "default",
                "dev": "wlan0",
                "gateway": config.upstream_gateway,
                "prefsrc": address,
            },
            {"dst": subnet, "dev": "wlan0", "prefsrc": address},
        ]

        result = manager.inspect()

        self.assertEqual(result.state, "active")
        self.assertEqual(result.upstream.connection, "wifi_hotspot")

    def test_wifi_controller_refuses_foreign_active_profile(self) -> None:
        cli = FakeNmcli()
        config = make_config(
            hotspot_ssid="Phone",
            hotspot_password="supersecret",
        )
        manager = NetworkManagerWifi(config, cli.run)
        manager.profile.create()
        cli.active["wlan0"] = "foreign"

        result = manager.inspect()

        self.assertEqual(result.error, WIFI_FOREIGN_MESSAGE)
        self.assertFalse(result.safe)

    def test_wifi_controller_reports_profile_drift(self) -> None:
        cli = FakeNmcli()
        config = make_config(
            hotspot_ssid="Phone",
            hotspot_password="supersecret",
        )
        manager = NetworkManagerWifi(config, cli.run)
        manager.profile.create()
        cli.profiles[WIFI_PROFILE_UUID]["ipv4.route-table"] = "254"

        inspection = manager.profile.inspect()

        self.assertEqual(inspection.state, "drifted")
        self.assertIn("ipv4.route-table", inspection.drifted_fields)

    def test_inventory_finds_foreign_wifi_and_ipheth_profiles(self) -> None:
        cli = FakeNmcli()
        cli.profiles["wifi-foreign"] = {
            "connection.uuid": "wifi-foreign",
            "connection.id": "Personal Wi-Fi",
            "connection.type": "802-11-wireless",
            "connection.interface-name": "wlan0",
        }
        cli.profiles["usb-foreign"] = {
            "connection.uuid": "usb-foreign",
            "connection.id": "Other iPhone",
            "connection.type": "802-3-ethernet",
            "match.driver": "ipheth",
        }
        inventory = NmInventory(cli.run)

        wifi = inventory.foreign_wifi_profiles(
            "wlan0",
            allowed_uuid=WIFI_PROFILE_UUID,
        )
        usb = inventory.foreign_ipheth_profiles(allowed_uuids=set())

        self.assertEqual([profile.uuid for profile in wifi], ["wifi-foreign"])
        self.assertEqual([profile.uuid for profile in usb], ["usb-foreign"])

    def test_preflight_requires_management_and_refuses_foreign_profiles(self) -> None:
        cli = FakeNmcli()
        config = make_config(
            mobile_connection="iphone_usb_wifi_fallback",
            hotspot_ssid="Phone",
            hotspot_password="supersecret",
        )
        self.assertEqual(
            inspect_nm_ownership(config, NmInventory(cli.run), None).errors,
            (MANAGEMENT_REQUIRED,),
        )
        cli.profiles["wifi-foreign"] = {
            "connection.uuid": "wifi-foreign",
            "connection.id": "Personal Wi-Fi",
            "connection.type": "802-11-wireless",
            "connection.interface-name": "wlan0",
        }
        cli.profiles["usb-foreign"] = {
            "connection.uuid": "usb-foreign",
            "connection.id": "Other iPhone",
            "connection.type": "802-3-ethernet",
            "match.driver": "ipheth",
        }

        result = inspect_nm_ownership(
            config,
            NmInventory(cli.run),
            ManagementBaseline("end0", "192.168.1.2/24"),
        )

        self.assertIn(WIFI_FOREIGN_PROFILE, result.errors)
        self.assertIn(USB_FOREIGN_PROFILE, result.errors)

    def test_preflight_classifies_matching_supervisor_profile_as_legacy(self) -> None:
        cli = FakeNmcli()
        config = make_config(
            hotspot_ssid="Phone",
            hotspot_password="supersecret",
        )
        cli.profiles["legacy"] = {
            "connection.uuid": "legacy",
            "connection.id": "Supervisor wlan0",
            "connection.type": "802-11-wireless",
            "connection.interface-name": "wlan0",
        }

        result = inspect_nm_ownership(
            config,
            NmInventory(cli.run),
            ManagementBaseline("end0", "192.168.1.2/24"),
        )

        self.assertEqual(result.errors, ())
        self.assertEqual(
            [profile.uuid for profile in result.legacy_wifi_profiles],
            ["legacy"],
        )


if __name__ == "__main__":
    unittest.main()
