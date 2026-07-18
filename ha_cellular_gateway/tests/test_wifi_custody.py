from __future__ import annotations

import unittest

from helpers import FakeRunner, make_config
from rootfs.app.networkmanager_wifi import NetworkManagerWifi
from rootfs.app.nm_profile_specs import WIFI_PROFILE_UUID
from rootfs.app.wifi_custody import parse_marker


def _up_commands(runner: FakeRunner) -> list[list[str]]:
    return [
        command
        for command in runner.commands
        if command[:6] == ["nmcli", "-w", "8", "connection", "up", "uuid"]
    ]


def _device_set_commands(commands: list[list[str]]) -> list[list[str]]:
    return [
        command
        for command in commands
        if command[:3] == ["nmcli", "device", "set"]
    ]


class WifiCustodianTests(unittest.TestCase):
    def _controller(
        self, runner: FakeRunner, clock: list[float]
    ) -> NetworkManagerWifi:
        config = make_config(
            hotspot_ssid="Phone",
            hotspot_password="supersecret",
        )
        controller = NetworkManagerWifi(
            config,
            lambda *args, **kwargs: runner.run(list(args), **kwargs),
            monotonic=lambda: clock[0],
        )
        controller.set_persist(lambda: None)
        return controller

    def test_marker_written_to_data_and_profile_before_device_change(self) -> None:
        runner = FakeRunner()
        controller = self._controller(runner, [1000.0])

        controller.claim("end0")

        self.assertTrue(controller.held)
        self.assertIsNotNone(controller.state())
        profile_marker = controller.custodian.read_profile_marker()
        self.assertIsNotNone(profile_marker)
        self.assertFalse(runner.nm_device_autoconnect["wlan0"])

    def test_marker_schema_rejects_extra_keys_and_has_no_secrets(self) -> None:
        valid = {
            "stable_device_identity": "02:00:00:00:00:a0",
            "prior_device_autoconnect": True,
            "prior_active_foreign_uuid": None,
        }
        self.assertIsNotNone(parse_marker(valid))
        self.assertIsNone(parse_marker({**valid, "hotspot_password": "secret"}))
        marker = parse_marker(valid)
        assert marker is not None
        serialised = marker.serialise()
        self.assertNotIn("Phone", serialised)
        self.assertNotIn("supersecret", serialised)

    def test_management_guard_blocks_claim_without_mutation(self) -> None:
        runner = FakeRunner()
        controller = self._controller(runner, [1000.0])

        errors = controller.claim("wlan0")

        self.assertTrue(errors)
        self.assertIn("management interface", errors[0].lower())
        self.assertNotIn(WIFI_PROFILE_UUID, runner.nm_profiles)
        self.assertTrue(runner.nm_device_autoconnect["wlan0"])

    def test_absent_target_waits_without_activation(self) -> None:
        runner = FakeRunner()
        controller = self._controller(runner, [1000.0])
        controller.claim("end0")

        result = controller.inspect()

        self.assertEqual(result.state, "waiting")
        self.assertTrue(result.safe)
        self.assertEqual(_up_commands(runner), [])

    def test_visible_target_triggers_single_activation(self) -> None:
        runner = FakeRunner()
        runner.nm_wifi_cache["wlan0"] = {"Phone"}
        controller = self._controller(runner, [1000.0])
        controller.claim("end0")

        result = controller.inspect()

        self.assertEqual(result.state, "active")
        self.assertEqual(len(_up_commands(runner)), 1)

    def test_activation_is_not_hammered_while_in_flight(self) -> None:
        runner = FakeRunner()
        runner.nm_wifi_cache["wlan0"] = {"Phone"}
        runner.nm_auto_activate = False
        clock = [1000.0]
        controller = self._controller(runner, clock)
        controller.claim("end0")

        first = controller.inspect()
        second = controller.inspect()

        self.assertEqual(len(_up_commands(runner)), 1)
        self.assertEqual(first.state, "connecting")
        self.assertEqual(second.state, "connecting")

    def test_authentication_failure_becomes_sticky(self) -> None:
        runner = FakeRunner()
        runner.nm_wifi_cache["wlan0"] = {"Phone"}
        runner.nm_auth_failure = True
        controller = self._controller(runner, [1000.0])
        controller.claim("end0")

        first = controller.inspect()
        second = controller.inspect()

        self.assertEqual(first.state, "auth_failed")
        self.assertTrue(first.safe)
        self.assertEqual(len(_up_commands(runner)), 1)
        self.assertEqual(controller.phase(), "attention")
        self.assertEqual(second.state, "auth_failed")

    def test_foreign_connection_mid_session_is_redisplaced(self) -> None:
        runner = FakeRunner()
        runner.nm_wifi_cache["wlan0"] = {"Phone"}
        controller = self._controller(runner, [1000.0])
        controller.claim("end0")
        runner.nm_profiles["A-D074"] = {
            "connection.uuid": "A-D074",
            "connection.id": "A-D074",
            "connection.type": "802-11-wireless",
            "connection.interface-name": "wlan0",
        }
        runner.nm_active["wlan0"] = "A-D074"

        result = controller.inspect()

        self.assertEqual(result.state, "connecting")
        self.assertNotIn("wlan0", runner.nm_active)
        self.assertIn("A-D074", runner.nm_profiles)

    def test_hard_rfkill_blocks_but_is_safely_unavailable(self) -> None:
        runner = FakeRunner()
        runner.nm_radio_hardware = False
        controller = self._controller(runner, [1000.0])

        errors = controller.claim("end0")
        result = controller.inspect()

        self.assertTrue(errors)
        self.assertEqual(controller.phase(), "blocked")
        self.assertEqual(result.state, "blocked")
        self.assertTrue(result.safe)
        self.assertNotIn(WIFI_PROFILE_UUID, runner.nm_profiles)
        self.assertTrue(runner.nm_device_autoconnect["wlan0"])

    def test_release_follows_renamed_device_by_stable_identity(self) -> None:
        runner = FakeRunner()
        controller = self._controller(runner, [1000.0])
        controller.claim("end0")
        self.assertFalse(runner.nm_device_autoconnect["wlan0"])

        identity = runner.nm_path.pop("wlan0")
        runner.nm_path["wlan1"] = identity
        runner.nm_device_autoconnect["wlan1"] = runner.nm_device_autoconnect.pop(
            "wlan0"
        )
        start = len(runner.commands)

        errors = controller.release("end0")
        device_sets = _device_set_commands(runner.commands[start:])

        self.assertEqual(errors, [])
        self.assertFalse(controller.restore_pending)
        self.assertIsNone(controller.state())
        self.assertTrue(runner.nm_device_autoconnect["wlan1"])
        self.assertNotIn("wlan0", runner.nm_device_autoconnect)
        self.assertTrue(device_sets)
        self.assertTrue(all(command[3] == "wlan1" for command in device_sets))

    def test_release_leaves_restoration_pending_when_marked_device_absent(
        self,
    ) -> None:
        runner = FakeRunner()
        controller = self._controller(runner, [1000.0])
        controller.claim("end0")

        runner.nm_path.pop("wlan0")
        runner.nm_device_autoconnect.pop("wlan0", None)
        start = len(runner.commands)

        errors = controller.release("end0")

        self.assertTrue(errors)
        self.assertTrue(controller.restore_pending)
        self.assertEqual(controller.phase(), "restoration_pending")
        self.assertIsNotNone(controller.state())
        self.assertIsNotNone(controller.marker)
        self.assertIn(WIFI_PROFILE_UUID, runner.nm_profiles)
        self.assertEqual(_device_set_commands(runner.commands[start:]), [])

        runner.nm_path["wlan0"] = "platform-fe300000.mmcnr"
        runner.nm_device_autoconnect["wlan0"] = False

        errors = controller.release("end0")

        self.assertEqual(errors, [])
        self.assertFalse(controller.restore_pending)
        self.assertIsNone(controller.state())
        self.assertTrue(runner.nm_device_autoconnect["wlan0"])

    def test_release_never_mutates_replacement_that_inherited_ifname(self) -> None:
        runner = FakeRunner()
        controller = self._controller(runner, [1000.0])
        controller.claim("end0")

        runner.nm_path["wlan0"] = "platform-replacement-usb"
        runner.nm_device_autoconnect["wlan0"] = True
        runner.nm_managed["wlan0"] = True
        start = len(runner.commands)

        errors = controller.release("end0")

        self.assertTrue(errors)
        self.assertTrue(controller.restore_pending)
        self.assertIsNotNone(controller.marker)
        self.assertTrue(runner.nm_device_autoconnect["wlan0"])
        self.assertIn(WIFI_PROFILE_UUID, runner.nm_profiles)
        self.assertEqual(_device_set_commands(runner.commands[start:]), [])

    def test_marker_is_stable_across_reconciles_and_restores_exactly(self) -> None:
        runner = FakeRunner()
        runner.nm_wifi_cache["wlan0"] = {"Phone"}
        runner.nm_profiles["A-D074"] = {
            "connection.uuid": "A-D074",
            "connection.id": "A-D074",
            "connection.type": "802-11-wireless",
            "connection.interface-name": "wlan0",
        }
        runner.nm_active["wlan0"] = "A-D074"
        controller = self._controller(runner, [1000.0])

        for _ in range(3):
            self.assertEqual(controller.claim("end0"), [])
            controller.inspect()

        marker = controller.state()
        assert marker is not None
        self.assertTrue(marker["prior_device_autoconnect"])
        self.assertEqual(marker["prior_active_foreign_uuid"], "A-D074")
        self.assertFalse(runner.nm_device_autoconnect["wlan0"])
        self.assertEqual(runner.nm_profiles["A-D074"]["connection.uuid"], "A-D074")

        self.assertEqual(controller.release("end0"), [])
        self.assertTrue(runner.nm_device_autoconnect["wlan0"])
        self.assertEqual(runner.nm_active.get("wlan0"), "A-D074")
        self.assertIsNone(controller.state())

    def test_release_retries_after_failed_foreign_reactivation(self) -> None:
        runner = FakeRunner()
        runner.nm_profiles["A-D074"] = {
            "connection.uuid": "A-D074",
            "connection.id": "A-D074",
            "connection.type": "802-11-wireless",
            "connection.interface-name": "wlan0",
        }
        runner.nm_active["wlan0"] = "A-D074"
        controller = self._controller(runner, [1000.0])
        self.assertEqual(controller.claim("end0"), [])

        runner.nm_up_failures.add("A-D074")
        errors = controller.release("end0")

        self.assertTrue(errors)
        self.assertTrue(controller.restore_pending)
        self.assertEqual(controller.phase(), "restoration_pending")
        self.assertIsNotNone(controller.state())
        self.assertIn(WIFI_PROFILE_UUID, runner.nm_profiles)
        self.assertFalse(runner.nm_device_autoconnect["wlan0"])
        self.assertIsNone(runner.nm_active.get("wlan0"))

        runner.nm_up_failures.discard("A-D074")
        errors = controller.release("end0")

        self.assertEqual(errors, [])
        self.assertFalse(controller.restore_pending)
        self.assertIsNone(controller.state())
        self.assertNotIn(WIFI_PROFILE_UUID, runner.nm_profiles)
        self.assertTrue(runner.nm_device_autoconnect["wlan0"])
        self.assertEqual(runner.nm_active.get("wlan0"), "A-D074")


if __name__ == "__main__":
    unittest.main()
