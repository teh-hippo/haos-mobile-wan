from __future__ import annotations

import unittest

from rootfs.app.errors import GatewayError
from rootfs.app.nm_profile_specs import USB_PROFILE_UUID, WIFI_PROFILE_UUID
from upstream_lifecycle_support import UpstreamLifecycleTestCase, genuine_profile


class UpstreamDeactivationTests(UpstreamLifecycleTestCase):
    def test_deactivate_removes_profile_and_restores_autoconnect(self) -> None:
        engine = self._engine()
        engine.upstream_lifecycle.activate(self._management())

        engine.upstream_lifecycle.deactivate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertNotIn(WIFI_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)
        self.assertTrue(engine.runner.networkmanager.nm_device_autoconnect["wlan0"])
        self.assertIsNone(engine.wifi.state())
        self.assertFalse(engine.wifi.held)

    def test_release_restores_prior_foreign_connection(self) -> None:
        engine = self._engine()
        engine.runner.networkmanager.nm_profiles["A-D074"] = genuine_profile()
        engine.runner.networkmanager.nm_active["wlan0"] = "A-D074"
        engine.upstream_lifecycle.activate(self._management())

        engine.upstream_lifecycle.deactivate(self._management())

        self.assertEqual(engine.runner.networkmanager.nm_active.get("wlan0"), "A-D074")
        self.assertTrue(engine.runner.networkmanager.nm_device_autoconnect["wlan0"])
        self.assertEqual(
            engine.runner.networkmanager.nm_profiles["A-D074"], genuine_profile()
        )

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

    def test_repeated_deactivate_skips_redundant_usb_cleanup(self) -> None:
        engine = self._engine(mobile_connection="iphone_usb")
        engine.upstream_lifecycle.activate(self._management())
        engine.upstream_lifecycle.deactivate(self._management())
        cleanup_calls: list[int] = []
        engine.upstream.cleanup = lambda: cleanup_calls.append(1)

        engine.upstream_lifecycle.deactivate(self._management())

        self.assertEqual(cleanup_calls, [])
        self.assertIsNone(engine.upstream_lifecycle.error)

    def test_persistent_journal_failure_blocks_deactivation(self) -> None:
        engine = self._engine()
        engine.upstream_lifecycle.activate(self._management())
        engine.upstream_lifecycle.journal.set_persist(
            lambda: (_ for _ in ()).throw(OSError("disk full"))
        )

        engine.upstream_lifecycle.deactivate(self._management())

        self.assertIn(
            "NetworkManager ownership journal failed",
            engine.upstream_lifecycle.error or "",
        )
        self.assertIn("disk full", engine.upstream_lifecycle.error or "")

    def test_wifi_release_failure_during_deactivation_is_reported(self) -> None:
        engine = self._engine()
        engine.upstream_lifecycle.activate(self._management())
        engine.wifi.release = lambda management_interface: (_ for _ in ()).throw(
            GatewayError("nmcli connection down failed")
        )

        engine.upstream_lifecycle.deactivate(self._management())

        self.assertIn(
            "NetworkManager profile cleanup failed",
            engine.upstream_lifecycle.error or "",
        )
        self.assertIn(
            "nmcli connection down failed",
            engine.upstream_lifecycle.error or "",
        )

    def test_drifted_profile_matching_identity_is_rescued_during_deactivation(
        self,
    ) -> None:
        engine = self._engine(mobile_connection="iphone_usb")
        engine.upstream_lifecycle.activate(self._management())
        self.assertEqual(engine.upstream.nm.profile.inspect().state, "exact")
        engine.runner.networkmanager.nm_profiles[USB_PROFILE_UUID][
            "ipv4.route-table"
        ] = "254"
        self.assertEqual(engine.upstream.nm.profile.inspect().state, "drifted")

        engine.upstream_lifecycle.deactivate(self._management())

        self.assertIsNone(engine.upstream_lifecycle.error)
        self.assertNotIn(USB_PROFILE_UUID, engine.runner.networkmanager.nm_profiles)
        self.assertIsNone(engine.upstream_lifecycle.journal.entry("iphone_usb"))


if __name__ == "__main__":
    unittest.main()
