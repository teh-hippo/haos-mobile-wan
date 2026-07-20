from __future__ import annotations

import unittest

from test_support.engine_fixtures import build_engine, make_config, sysctl_values
from test_support.runner import FakeRunner
from upstream_lifecycle_support import UpstreamLifecycleTestCase, genuine_profile


class UpstreamStateTests(UpstreamLifecycleTestCase):
    def test_restart_preserves_marker_and_restores_exactly(self) -> None:
        runner = FakeRunner()
        runner.networkmanager.nm_profiles["A-D074"] = genuine_profile()
        runner.networkmanager.nm_active["wlan0"] = "A-D074"
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
        primer.upstream_lifecycle.activate(self._management())
        baseline = primer.wifi.state()
        self.assertIsNotNone(baseline)
        self.assertFalse(runner.networkmanager.nm_device_autoconnect["wlan0"])

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
        self.assertTrue(runner.networkmanager.nm_device_autoconnect["wlan0"])
        self.assertEqual(runner.networkmanager.nm_active.get("wlan0"), "A-D074")
        self.assertEqual(runner.networkmanager.nm_profiles["A-D074"], genuine_profile())
        self.assertIsNone(engine.wifi.state())

    def test_invalid_persistent_custody_state_is_rejected(self) -> None:
        engine = self._engine()

        error = engine.wifi.load_state({"stable_device_identity": 42})

        self.assertIn("custody state is invalid", error or "")


if __name__ == "__main__":
    unittest.main()
