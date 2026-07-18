from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import FakeRunner, make_config, sysctl_values
from rootfs.app.const import (
    IPHONE_USB,
    IPHONE_USB_WIFI_FALLBACK,
    LEGACY_WIFI_MIGRATE_MATCHING,
)
from rootfs.app.gateway import GatewayEngine
from rootfs.app.management import ManagementBaseline
from rootfs.app.nm_profile import NmProfile
from rootfs.app.nm_profile_specs import (
    USB_PROFILE_UUID,
    WIFI_PROFILE_UUID,
    wifi_profile_spec,
)
from rootfs.app.state import StateStore
from rootfs.app.upstream_lifecycle import (
    LEGACY_WIFI_MANUAL_ERROR,
    UpstreamLifecycle,
)
from rootfs.app.nm_migration import (
    LEGACY_WIFI_DELETE_ERROR,
    LEGACY_WIFI_MISMATCH_ERROR,
)


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
        return GatewayEngine(
            config,
            runner=runner,
            read_text=lambda path: sysctl_values()[path],
            state_path=self.state_path,
        )

    @staticmethod
    def _management() -> ManagementBaseline:
        return ManagementBaseline("end0", "192.168.1.2/24")

    def test_wifi_activation_creates_only_app_profile(self) -> None:
        engine = self._engine()

        engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertIn(WIFI_PROFILE_UUID, engine.runner.nm_profiles)
        self.assertNotIn(USB_PROFILE_UUID, engine.runner.nm_profiles)
        self.assertEqual(
            engine.upstream_lifecycle.state()["phase"],
            "active",
        )
        owned = engine.upstream_lifecycle.state()["owned"]
        self.assertEqual(
            owned["wifi_hotspot"]["uuid"],
            WIFI_PROFILE_UUID,
        )
        diagnostics = engine.upstream_lifecycle.diagnostics()
        self.assertEqual(diagnostics["phase"], "active")
        self.assertEqual(
            diagnostics["profile_states"]["wifi_hotspot"],
            "exact",
        )
        self.assertEqual(
            diagnostics["owned_profiles"]["wifi_hotspot"],
            WIFI_PROFILE_UUID,
        )

    def test_fallback_activation_creates_warm_standby_profiles(self) -> None:
        engine = self._engine(
            mobile_connection=IPHONE_USB_WIFI_FALLBACK,
        )

        engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertIn(WIFI_PROFILE_UUID, engine.runner.nm_profiles)
        self.assertIn(USB_PROFILE_UUID, engine.runner.nm_profiles)

    def test_deactivate_removes_exact_app_profiles(self) -> None:
        engine = self._engine(
            mobile_connection=IPHONE_USB_WIFI_FALLBACK,
        )
        engine.upstream_lifecycle.activate(self._management())

        engine.upstream_lifecycle.deactivate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertNotIn(WIFI_PROFILE_UUID, engine.runner.nm_profiles)
        self.assertNotIn(USB_PROFILE_UUID, engine.runner.nm_profiles)
        self.assertIsNone(engine.upstream_lifecycle.state())

    def test_missing_owned_profile_is_recreated_while_enabled(self) -> None:
        engine = self._engine()
        engine.upstream_lifecycle.activate(self._management())
        del engine.runner.nm_profiles[WIFI_PROFILE_UUID]

        engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertIn(WIFI_PROFILE_UUID, engine.runner.nm_profiles)

    def test_disabled_restart_removes_journaled_profile(self) -> None:
        runner = FakeRunner()
        config = make_config(
            enabled=False,
            hotspot_ssid="Phone",
            hotspot_password="supersecret",
        )
        NmProfile(
            lambda *args, **kwargs: runner.run(list(args), **kwargs),
            wifi_profile_spec(config),
        ).create()
        StateStore(self.state_path).save(
            owned=None,
            profiles={
                "phase": "active",
                "owned": {"wifi_hotspot": WIFI_PROFILE_UUID},
            },
        )
        engine = GatewayEngine(
            config,
            runner=runner,
            read_text=lambda path: sysctl_values()[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"

        engine.reconcile()

        self.assertNotIn(WIFI_PROFILE_UUID, runner.nm_profiles)
        self.assertIsNone(engine.upstream_lifecycle.state())

    def test_disabled_restart_uses_historical_fingerprint_after_config_change(
        self,
    ) -> None:
        runner = FakeRunner()
        old_config = make_config(
            enabled=True,
            hotspot_ssid="OldPhone",
            hotspot_password="oldsecret",
        )
        old_spec = wifi_profile_spec(old_config)
        NmProfile(
            lambda *args, **kwargs: runner.run(list(args), **kwargs),
            old_spec,
        ).create()
        StateStore(self.state_path).save(
            owned=None,
            profiles={
                "phase": "active",
                "owned": {
                    "wifi_hotspot": {
                        "uuid": old_spec.uuid,
                        "fingerprint": old_spec.fingerprint,
                    }
                },
            },
        )
        new_config = make_config(
            enabled=False,
            hotspot_ssid="NewPhone",
            hotspot_password="newsecret",
        )
        engine = GatewayEngine(
            new_config,
            runner=runner,
            read_text=lambda path: sysctl_values()[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"

        engine.reconcile()

        self.assertNotIn(WIFI_PROFILE_UUID, runner.nm_profiles)

    def test_disabled_restart_removes_partial_claimed_profile(self) -> None:
        runner = FakeRunner()
        config = make_config(
            enabled=False,
            hotspot_ssid="Phone",
            hotspot_password="supersecret",
        )
        spec = wifi_profile_spec(config)
        runner.nm_profiles[spec.uuid] = {
            "connection.uuid": spec.uuid,
            "connection.id": spec.name,
            "connection.type": spec.connection_type,
        }
        StateStore(self.state_path).save(
            owned=None,
            profiles={
                "phase": "acquiring",
                "owned": {
                    "wifi_hotspot": {
                        "uuid": spec.uuid,
                        "fingerprint": spec.fingerprint,
                    }
                },
            },
        )
        engine = GatewayEngine(
            config,
            runner=runner,
            read_text=lambda path: sysctl_values()[path],
            state_path=self.state_path,
        )
        engine.safety.find_downstream = lambda *_a, **_k: "enx001122334455"

        engine.reconcile()

        self.assertNotIn(WIFI_PROFILE_UUID, runner.nm_profiles)

    def test_unclaimed_drifted_profile_is_never_deleted(self) -> None:
        engine = self._engine(enabled=False)
        spec = wifi_profile_spec(engine.config)
        NmProfile(engine._run, spec).create()
        engine.runner.nm_profiles[spec.uuid]["ipv4.route-table"] = "254"

        engine.reconcile()

        self.assertIn(WIFI_PROFILE_UUID, engine.runner.nm_profiles)
        self.assertIn(
            "unexpected settings",
            engine.upstream_lifecycle.error or "",
        )

    def test_activation_requires_management_before_mutation(self) -> None:
        engine = self._engine()

        engine.upstream_lifecycle.activate(None)

        self.assertIn(
            "Management interface is unavailable",
            engine.upstream_lifecycle.error or "",
        )
        self.assertEqual(engine.runner.nm_profiles, {})

    def test_foreign_wifi_profile_blocks_activation_without_mutation(self) -> None:
        engine = self._engine()
        engine.runner.nm_profiles["foreign"] = {
            "connection.uuid": "foreign",
            "connection.id": "Personal Wi-Fi",
            "connection.type": "802-11-wireless",
            "connection.interface-name": "wlan0",
        }

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn(
            "foreign NetworkManager profile",
            engine.upstream_lifecycle.error or "",
        )
        self.assertNotIn(WIFI_PROFILE_UUID, engine.runner.nm_profiles)

    def test_foreign_profile_releases_existing_app_profile(self) -> None:
        engine = self._engine()
        engine.upstream_lifecycle.activate(self._management())
        engine.runner.nm_profiles["foreign"] = {
            "connection.uuid": "foreign",
            "connection.id": "Personal Wi-Fi",
            "connection.type": "802-11-wireless",
            "connection.interface-name": "wlan0",
        }

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn(
            "foreign NetworkManager profile",
            engine.upstream_lifecycle.error or "",
        )
        self.assertNotIn(WIFI_PROFILE_UUID, engine.runner.nm_profiles)

    def test_legacy_wifi_defaults_to_manual_cleanup(self) -> None:
        engine = self._engine()
        engine.runner.nm_profiles["legacy"] = {
            "connection.uuid": "legacy",
            "connection.id": "Supervisor wlan0",
            "connection.type": "802-11-wireless",
            "connection.interface-name": "wlan0",
            "802-11-wireless.ssid": "Phone",
            "ipv4.addresses": "172.20.10.4/28",
        }

        engine.upstream_lifecycle.activate(self._management())

        self.assertEqual(
            engine.upstream_lifecycle.error,
            LEGACY_WIFI_MANUAL_ERROR,
        )
        self.assertIn("legacy", engine.runner.nm_profiles)

    def test_matching_legacy_wifi_can_be_migrated_explicitly(self) -> None:
        engine = self._engine(
            legacy_wifi_migration=LEGACY_WIFI_MIGRATE_MATCHING,
        )
        engine.runner.nm_profiles["legacy"] = {
            "connection.uuid": "legacy",
            "connection.id": "Supervisor wlan0",
            "connection.type": "802-11-wireless",
            "connection.interface-name": "wlan0",
            "802-11-wireless.ssid": "Phone",
            "ipv4.addresses": "172.20.10.4/28",
        }

        engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertNotIn("legacy", engine.runner.nm_profiles)
        self.assertIn(WIFI_PROFILE_UUID, engine.runner.nm_profiles)

    def test_matching_bound_and_unbound_legacy_wifi_profiles_are_migrated(
        self,
    ) -> None:
        engine = self._engine(
            legacy_wifi_migration=LEGACY_WIFI_MIGRATE_MATCHING,
        )
        for uuid, interface in (
            ("bound", "wlan0"),
            ("unbound", ""),
        ):
            engine.runner.nm_profiles[uuid] = {
                "connection.uuid": uuid,
                "connection.id": "Supervisor wlan0",
                "connection.type": "802-11-wireless",
                "connection.interface-name": interface,
                "802-11-wireless.ssid": "Phone",
                "ipv4.addresses": "172.20.10.4/28",
            }

        engine.upstream_lifecycle.activate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertNotIn("bound", engine.runner.nm_profiles)
        self.assertNotIn("unbound", engine.runner.nm_profiles)
        self.assertIn(WIFI_PROFILE_UUID, engine.runner.nm_profiles)

    def test_legacy_wifi_address_substring_is_not_a_match(self) -> None:
        engine = self._engine(
            legacy_wifi_migration=LEGACY_WIFI_MIGRATE_MATCHING,
        )
        engine.runner.nm_profiles["legacy"] = {
            "connection.uuid": "legacy",
            "connection.id": "Supervisor wlan0",
            "connection.type": "802-11-wireless",
            "connection.interface-name": "wlan0",
            "802-11-wireless.ssid": "Phone",
            "ipv4.addresses": "1172.20.10.4/28",
        }

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn(
            LEGACY_WIFI_MISMATCH_ERROR,
            engine.upstream_lifecycle.error or "",
        )
        self.assertIn("legacy", engine.runner.nm_profiles)

    def test_mixed_legacy_wifi_candidates_are_not_partially_deleted(self) -> None:
        engine = self._engine(
            legacy_wifi_migration=LEGACY_WIFI_MIGRATE_MATCHING,
        )
        for uuid, address in (
            ("matching", "172.20.10.4/28"),
            ("mismatch", "172.20.11.4/28"),
        ):
            engine.runner.nm_profiles[uuid] = {
                "connection.uuid": uuid,
                "connection.id": "Supervisor wlan0",
                "connection.type": "802-11-wireless",
                "connection.interface-name": "wlan0",
                "802-11-wireless.ssid": "Phone",
                "ipv4.addresses": address,
            }

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn("matching", engine.runner.nm_profiles)
        self.assertIn("mismatch", engine.runner.nm_profiles)

    def test_failed_legacy_wifi_delete_is_reported(self) -> None:
        engine = self._engine(
            legacy_wifi_migration=LEGACY_WIFI_MIGRATE_MATCHING,
        )
        engine.runner.nm_profiles["legacy"] = {
            "connection.uuid": "legacy",
            "connection.id": "Supervisor wlan0",
            "connection.type": "802-11-wireless",
            "connection.interface-name": "wlan0",
            "802-11-wireless.ssid": "Phone",
            "ipv4.addresses": "172.20.10.4/28",
        }
        engine.runner.nm_delete_fail = True

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn(
            LEGACY_WIFI_DELETE_ERROR,
            engine.upstream_lifecycle.error or "",
        )
        self.assertIn("legacy", engine.runner.nm_profiles)

    def test_usb_cleanup_failure_is_reported_without_escaping(self) -> None:
        engine = self._engine(mobile_connection=IPHONE_USB)
        engine.upstream.cleanup = lambda: (_ for _ in ()).throw(
            ProcessLookupError("already stopped")
        )

        engine.upstream_lifecycle.deactivate(self._management())

        self.assertIn(
            "iPhone USB cleanup failed",
            engine.upstream_lifecycle.error or "",
        )

    def test_invalid_persistent_profile_state_is_rejected(self) -> None:
        engine = self._engine()
        lifecycle: UpstreamLifecycle = engine.upstream_lifecycle

        error = lifecycle.load_state({"wifi_hotspot": 42})

        self.assertIn("ownership is invalid", error or "")

    def test_journal_failure_prevents_profile_creation(self) -> None:
        engine = self._engine()
        engine.upstream_lifecycle.set_persist(
            lambda: (_ for _ in ()).throw(OSError("disk full"))
        )

        engine.upstream_lifecycle.activate(self._management())

        self.assertIn(
            "ownership journal failed",
            engine.upstream_lifecycle.error or "",
        )
        self.assertEqual(engine.runner.nm_profiles, {})


if __name__ == "__main__":
    unittest.main()
