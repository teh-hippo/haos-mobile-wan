from __future__ import annotations

import unittest

from rootfs.app.nm_profile_specs import WIFI_PROFILE_UUID
from test_support.engine_fixtures import build_engine, make_config, sysctl_values
from test_support.runner import FakeRunner
from upstream_lifecycle_support import UpstreamLifecycleTestCase


class UpstreamRecoveryTests(UpstreamLifecycleTestCase):
    def test_startup_recovery_restores_from_persisted_marker(self) -> None:
        primer = self._engine()
        primer.upstream_lifecycle.activate(self._management())
        runner = primer.runner
        self.assertFalse(runner.networkmanager.nm_device_autoconnect["wlan0"])

        engine = build_engine(
            make_config(
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            runner=runner,
            read_text=lambda path: sysctl_values()[path],
            state_path=self.state_path,
        )

        engine.upstream_lifecycle.recover(self._management())

        self.assertNotIn(WIFI_PROFILE_UUID, runner.networkmanager.nm_profiles)
        self.assertTrue(runner.networkmanager.nm_device_autoconnect["wlan0"])
        self.assertIsNone(engine.wifi.state())

    def test_startup_recovery_reclaims_fixed_uuid_without_marker(self) -> None:
        runner = FakeRunner()
        config = make_config(
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
        runner.networkmanager.nm_device_autoconnect["wlan0"] = True

        engine = build_engine(
            config,
            runner=runner,
            read_text=lambda path: sysctl_values()[path],
            state_path=self.state_path,
        )

        engine.upstream_lifecycle.recover(self._management())

        self.assertNotIn(WIFI_PROFILE_UUID, runner.networkmanager.nm_profiles)
        self.assertTrue(runner.networkmanager.nm_device_autoconnect["wlan0"])


if __name__ == "__main__":
    unittest.main()
