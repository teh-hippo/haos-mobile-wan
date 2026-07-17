from __future__ import annotations

import unittest

from helpers import make_config
from rootfs.app.upstream_lifecycle import RETRY_SECONDS, UpstreamLifecycle


class FakeIPhone:
    def __init__(self) -> None:
        self.cleanup_calls = 0

    def cleanup(self) -> None:
        self.cleanup_calls += 1


class UpstreamLifecycleTests(unittest.TestCase):
    def _lifecycle(self, configure, clock=lambda: 100.0):
        iphone = FakeIPhone()
        lifecycle = UpstreamLifecycle(
            make_config(
                hotspot_ssid="Phone",
                hotspot_password="supersecret",
            ),
            iphone,
            configure=configure,
            clock=clock,
        )
        return lifecycle, iphone

    def test_deactivate_stops_usb_and_disables_hotspot_once(self) -> None:
        calls: list[bool] = []
        lifecycle, iphone = self._lifecycle(
            lambda config, *, enabled: calls.append(enabled) or None
        )

        lifecycle.deactivate("eth0")
        lifecycle.deactivate("eth0")

        self.assertEqual(iphone.cleanup_calls, 1)
        self.assertEqual(calls, [False])
        self.assertIsNone(lifecycle.error)

    def test_activate_reenables_hotspot_after_dormancy(self) -> None:
        calls: list[bool] = []
        lifecycle, _ = self._lifecycle(
            lambda config, *, enabled: calls.append(enabled) or None
        )

        lifecycle.deactivate("eth0")
        lifecycle.activate("eth0")
        lifecycle.activate("eth0")

        self.assertEqual(calls, [False, True])

    def test_management_interface_is_never_reconfigured(self) -> None:
        calls: list[bool] = []
        lifecycle, _ = self._lifecycle(
            lambda config, *, enabled: calls.append(enabled) or None
        )

        lifecycle.activate("wlan0")

        self.assertEqual(calls, [])
        self.assertIn("management interface", lifecycle.error or "")

    def test_failed_hotspot_change_is_rate_limited(self) -> None:
        now = [100.0]
        calls: list[bool] = []
        lifecycle, _ = self._lifecycle(
            lambda config, *, enabled: calls.append(enabled) or "failed",
            clock=lambda: now[0],
        )

        lifecycle.activate("eth0")
        lifecycle.activate("eth0")
        now[0] += RETRY_SECONDS
        lifecycle.activate("eth0")

        self.assertEqual(calls, [True, True])
        self.assertEqual(lifecycle.error, "failed")


if __name__ == "__main__":
    unittest.main()
