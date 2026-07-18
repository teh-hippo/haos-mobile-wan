from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import FakeRunner, build_engine, make_config, sysctl_values
from rootfs.app.const import IPHONE_USB_WIFI_FALLBACK
from rootfs.app.gateway import GatewayEngine
from rootfs.app.management import ManagementBaseline
from rootfs.app.nm_migration import LINEAGE_WIFI_DELETE_ERROR
from rootfs.app.nm_profile_specs import USB_PROFILE_UUID, WIFI_PROFILE_UUID


def _legacy_profile(uuid: str, interface: str) -> dict[str, str]:
    return {
        "connection.uuid": uuid,
        "connection.id": "Supervisor wlan0",
        "connection.type": "802-11-wireless",
        "connection.interface-name": interface,
        "802-11-wireless.ssid": "Phone",
        "ipv4.addresses": "172.20.10.4/28",
    }


def _genuine_profile() -> dict[str, str]:
    return {
        "connection.uuid": "A-D074",
        "connection.id": "A-D074",
        "connection.type": "802-11-wireless",
        "connection.interface-name": "wlan0",
        "ipv4.addresses": "",
    }


class UpstreamLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.state_path = Path(self.directory.name) / "state.json"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _engine(self, **overrides: object) -> GatewayEngine:
        runner = FakeRunner()
        config = make_config(
            hotspot_ssid="Phone",
            hotspot_password="supersecret",
            **overrides,
        )
        return build_engine(
            config,
            runner=runner,
            read_text=lambda path: sysctl_values()[path],
            state_path=self.state_path,
        )

    @staticmethod
    def _management() -> ManagementBaseline:
        return ManagementBaseline("end0", "192.168.1.2/24")

    def test_wifi_claim_creates_profile_and_gates_device(self) -> None:
        engine = self._engine()

        engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertIn(WIFI_PROFILE_UUID, engine.runner.nm_profiles)
        self.assertNotIn(USB_PROFILE_UUID, engine.runner.nm_profiles)
        self.assertFalse(engine.runner.nm_device_autoconnect["wlan0"])
        self.assertTrue(engine.wifi.held)
        self.assertEqual(engine.wifi.phase(), "held")
        marker = engine.wifi.state()
        self.assertIsNotNone(marker)
        self.assertTrue(marker["prior_device_autoconnect"])
        self.assertIsNone(marker["prior_active_foreign_uuid"])

    def test_fallback_claims_wifi_and_usb(self) -> None:
        engine = self._engine(mobile_connection=IPHONE_USB_WIFI_FALLBACK)

        engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertIn(WIFI_PROFILE_UUID, engine.runner.nm_profiles)
        self.assertIn(USB_PROFILE_UUID, engine.runner.nm_profiles)

    def test_deactivate_removes_profile_and_restores_autoconnect(self) -> None:
        engine = self._engine()
        engine.upstream_lifecycle.activate(self._management())

        engine.upstream_lifecycle.deactivate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertNotIn(WIFI_PROFILE_UUID, engine.runner.nm_profiles)
        self.assertTrue(engine.runner.nm_device_autoconnect["wlan0"])
        self.assertIsNone(engine.wifi.state())
        self.assertFalse(engine.wifi.held)

    def test_genuine_foreign_profile_is_preserved_and_displaced(self) -> None:
        engine = self._engine()
        engine.runner.nm_profiles["A-D074"] = _genuine_profile()
        engine.runner.nm_active["wlan0"] = "A-D074"

        engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertEqual(engine.runner.nm_profiles["A-D074"], _genuine_profile())
        self.assertNotIn("wlan0", engine.runner.nm_active)
        marker = engine.wifi.state()
        assert marker is not None
        self.assertEqual(marker["prior_active_foreign_uuid"], "A-D074")

    def test_release_restores_prior_foreign_connection(self) -> None:
        engine = self._engine()
        engine.runner.nm_profiles["A-D074"] = _genuine_profile()
        engine.runner.nm_active["wlan0"] = "A-D074"
        engine.upstream_lifecycle.activate(self._management())

        engine.upstream_lifecycle.deactivate(self._management())

        self.assertEqual(engine.runner.nm_active.get("wlan0"), "A-D074")
        self.assertTrue(engine.runner.nm_device_autoconnect["wlan0"])
        self.assertEqual(engine.runner.nm_profiles["A-D074"], _genuine_profile())

    def test_legacy_lineage_cleaned_while_genuine_foreign_preserved(self) -> None:
        engine = self._engine()
        engine.runner.nm_profiles["bound"] = _legacy_profile("bound", "wlan0")
        engine.runner.nm_profiles["unbound"] = _legacy_profile("unbound", "")
        engine.runner.nm_profiles["A-D074"] = _genuine_profile()

        engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertNotIn("bound", engine.runner.nm_profiles)
        self.assertNotIn("unbound", engine.runner.nm_profiles)
        self.assertIn("A-D074", engine.runner.nm_profiles)
        self.assertIn(WIFI_PROFILE_UUID, engine.runner.nm_profiles)

    def test_lineage_address_mismatch_is_not_cleaned(self) -> None:
        engine = self._engine()
        profile = _legacy_profile("mismatch", "wlan0")
        profile["ipv4.addresses"] = "172.20.11.4/28"
        engine.runner.nm_profiles["mismatch"] = profile

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn("mismatch", engine.runner.nm_profiles)

    def test_lineage_ssid_mismatch_preserves_genuine_profile(self) -> None:
        engine = self._engine()
        profile = _legacy_profile("same-name", "wlan0")
        profile["802-11-wireless.ssid"] = "Neighbour"
        engine.runner.nm_profiles["same-name"] = profile

        engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertIn("same-name", engine.runner.nm_profiles)
        self.assertEqual(
            engine.runner.nm_profiles["same-name"]["802-11-wireless.ssid"],
            "Neighbour",
        )

    def test_failed_lineage_delete_is_reported(self) -> None:
        engine = self._engine()
        engine.runner.nm_profiles["bound"] = _legacy_profile("bound", "wlan0")
        engine.runner.nm_delete_fail = True

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn(
            LINEAGE_WIFI_DELETE_ERROR,
            engine.upstream_lifecycle.error or "",
        )
        self.assertIn("bound", engine.runner.nm_profiles)

    def test_activation_requires_management_before_mutation(self) -> None:
        engine = self._engine()

        engine.upstream_lifecycle.activate(None)

        self.assertIn(
            "Management interface is unavailable",
            engine.upstream_lifecycle.error or "",
        )
        self.assertNotIn(WIFI_PROFILE_UUID, engine.runner.nm_profiles)

    def test_unmanaged_adapter_blocks_without_mutation(self) -> None:
        engine = self._engine()
        engine.runner.nm_managed["wlan0"] = False

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn("does not manage", engine.upstream_lifecycle.error or "")
        self.assertNotIn(WIFI_PROFILE_UUID, engine.runner.nm_profiles)
        self.assertTrue(engine.runner.nm_device_autoconnect["wlan0"])

    def test_hard_rfkill_blocks_without_mutation(self) -> None:
        engine = self._engine()
        engine.runner.nm_radio_hardware = False

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn("hardware-blocked", engine.upstream_lifecycle.error or "")
        self.assertNotIn(WIFI_PROFILE_UUID, engine.runner.nm_profiles)

    def test_disabled_restart_restores_from_persisted_marker(self) -> None:
        primer = self._engine()
        primer.upstream_lifecycle.activate(self._management())
        runner = primer.runner
        self.assertFalse(runner.nm_device_autoconnect["wlan0"])

        engine = build_engine(
            make_config(
                enabled=False,
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            runner=runner,
            read_text=lambda path: sysctl_values()[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"

        engine.reconcile()

        self.assertNotIn(WIFI_PROFILE_UUID, runner.nm_profiles)
        self.assertTrue(runner.nm_device_autoconnect["wlan0"])
        self.assertIsNone(engine.wifi.state())

    def test_disabled_restart_reclaims_fixed_uuid_without_marker(self) -> None:
        runner = FakeRunner()
        config = make_config(
            enabled=False,
            hotspot_ssid="Phone",
            hotspot_password="supersecret",
        )
        primer = build_engine(
            config,
            runner=runner,
            read_text=lambda path: sysctl_values()[path],
            state_path=self.state_path,
        )
        primer.wifi.profile.create()
        runner.nm_device_autoconnect["wlan0"] = True

        engine = build_engine(
            config,
            runner=runner,
            read_text=lambda path: sysctl_values()[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"

        engine.reconcile()

        self.assertNotIn(WIFI_PROFILE_UUID, runner.nm_profiles)
        self.assertTrue(runner.nm_device_autoconnect["wlan0"])

    def test_wifi_profile_drift_blocks_without_deletion(self) -> None:
        engine = self._engine()
        engine.wifi.profile.create()
        engine.runner.nm_profiles[WIFI_PROFILE_UUID]["ipv4.route-table"] = "254"

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn("unexpected settings", engine.upstream_lifecycle.error or "")
        self.assertIn(WIFI_PROFILE_UUID, engine.runner.nm_profiles)

    def test_usb_cleanup_failure_is_reported_without_escaping(self) -> None:
        engine = self._engine(mobile_connection="iphone_usb")
        engine.upstream.cleanup = lambda: (_ for _ in ()).throw(
            ProcessLookupError("already stopped")
        )

        engine.upstream_lifecycle.deactivate(self._management())

        self.assertIn(
            "iPhone USB cleanup failed",
            engine.upstream_lifecycle.error or "",
        )

    def test_enabled_restart_preserves_marker_and_restores_exactly(self) -> None:
        runner = FakeRunner()
        runner.nm_profiles["A-D074"] = _genuine_profile()
        runner.nm_active["wlan0"] = "A-D074"
        config = make_config(
            enabled=True,
            hotspot_ssid="Phone",
            hotspot_password="supersecret",
        )
        primer = build_engine(
            config,
            runner=runner,
            read_text=lambda path: sysctl_values()[path],
            state_path=self.state_path,
        )
        primer.upstream_lifecycle.activate(self._management())
        baseline = primer.wifi.state()
        self.assertIsNotNone(baseline)
        self.assertFalse(runner.nm_device_autoconnect["wlan0"])

        engine = build_engine(
            config,
            runner=runner,
            read_text=lambda path: sysctl_values()[path],
            state_path=self.state_path,
        )
        self.assertEqual(engine.wifi.state(), baseline)

        for _ in range(2):
            engine.upstream_lifecycle.activate(self._management())
            self.assertIsNone(engine.upstream_lifecycle.error)
            self.assertEqual(engine.wifi.state(), baseline)

        engine.upstream_lifecycle.deactivate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertTrue(runner.nm_device_autoconnect["wlan0"])
        self.assertEqual(runner.nm_active.get("wlan0"), "A-D074")
        self.assertEqual(runner.nm_profiles["A-D074"], _genuine_profile())
        self.assertIsNone(engine.wifi.state())

    def test_combined_mode_keeps_usb_owned_while_wifi_safely_unavailable(
        self,
    ) -> None:
        engine = self._engine(mobile_connection=IPHONE_USB_WIFI_FALLBACK)
        engine.runner.nm_radio_hardware = False

        def usb_churn_commands() -> list[list[str]]:
            return [
                command
                for command in engine.runner.commands
                if (
                    command[:3] == ["nmcli", "connection", "add"]
                    and USB_PROFILE_UUID in command
                )
                or command[:4]
                == ["nmcli", "connection", "delete", "uuid"]
                and command[-1] == USB_PROFILE_UUID
            ]

        engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertIn(USB_PROFILE_UUID, engine.runner.nm_profiles)
        self.assertNotIn(WIFI_PROFILE_UUID, engine.runner.nm_profiles)
        self.assertEqual(engine.wifi.phase(), "blocked")
        usb_entry = engine.upstream_lifecycle.journal.entry("iphone_usb")
        assert isinstance(usb_entry, dict)
        self.assertEqual(usb_entry.get("uuid"), USB_PROFILE_UUID)
        churn_after_first = len(usb_churn_commands())

        for _ in range(2):
            engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertIn(USB_PROFILE_UUID, engine.runner.nm_profiles)
        self.assertEqual(
            engine.upstream_lifecycle.journal.entry("iphone_usb"),
            usb_entry,
        )
        self.assertEqual(len(usb_churn_commands()), churn_after_first)

    def test_invalid_persistent_custody_state_is_rejected(self) -> None:
        engine = self._engine()

        error = engine.wifi.load_state({"stable_device_identity": 42})

        self.assertIn("custody state is invalid", error or "")


if __name__ == "__main__":
    unittest.main()
