from __future__ import annotations

import unittest

from rootfs.app.nm_profile_specs import WIFI_PROFILE_UUID
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


if __name__ == "__main__":
    unittest.main()
