"""Lease-grace timing tests for IPhoneUsbUpstream.resolve()."""

from __future__ import annotations

import unittest

from rootfs.app.networkmanager import NetworkManagerResult
from rootfs.app.nm_profile import ACTIVATION_COOLDOWN_SECONDS
from rootfs.app.nm_profile_specs import (
    USB_DHCP_TIMEOUT_SECONDS as DHCP_TIMEOUT_SECONDS,
)
from rootfs.app.upstream_iphone import IPhoneUsbUpstream
from test_support.iphone_usb_fixtures import (
    FakeNetworkManager,
    IPhoneUsbUpstreamHarness,
    usb_upstream,
)


class IPhoneUsbLeaseGraceTests(IPhoneUsbUpstreamHarness):
    def test_missing_lease_within_grace_keeps_last_upstream(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        network_manager = FakeNetworkManager(
            [
                NetworkManagerResult(usb_upstream(), "active", None, True),
                NetworkManagerResult(None, "waiting", "renewing", True),
                NetworkManagerResult(None, "waiting", "renewing", True),
            ]
        )
        manager = self._manager(runner, network_manager)

        first, _ = manager.resolve()
        assert first is not None
        self.clock[0] += 5
        grace, errors = manager.resolve()

        self.assertEqual(errors, [])
        self.assertEqual(grace, usb_upstream())
        self.assertEqual(manager.pairing_state, "paired")

        self.clock[0] += IPhoneUsbUpstream.LEASE_GRACE_SECONDS
        expired, errors = manager.resolve()

        self.assertIsNone(expired)
        self.assertEqual(manager.pairing_state, "waiting_for_profile")

    def test_lease_grace_covers_networkmanager_activation_cooldown(self) -> None:
        self.assertGreater(
            IPhoneUsbUpstream.LEASE_GRACE_SECONDS,
            ACTIVATION_COOLDOWN_SECONDS,
        )
        self.assertGreater(
            IPhoneUsbUpstream.LEASE_GRACE_SECONDS,
            DHCP_TIMEOUT_SECONDS,
        )

    def test_grace_is_rejected_when_profile_continuity_is_lost(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        network_manager = FakeNetworkManager(
            [
                NetworkManagerResult(usb_upstream(), "active", None, True),
                NetworkManagerResult(None, "waiting", "renewing", True),
            ]
        )
        manager = self._manager(runner, network_manager)
        manager.resolve()
        network_manager.continuous = False

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(errors, ["renewing"])

    def test_networkmanager_inspection_failure_uses_continuous_grace(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        network_manager = FakeNetworkManager(
            [NetworkManagerResult(usb_upstream(), "active", None, True)]
        )
        manager = self._manager(runner, network_manager)
        first, _ = manager.resolve()
        assert first is not None
        network_manager.inspect_error = OSError("NetworkManager restarting")

        grace, errors = manager.resolve()

        self.assertEqual(grace, first)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
