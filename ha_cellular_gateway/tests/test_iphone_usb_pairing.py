"""Device presence, pairing, carrier, and fallback-gating tests for
IPhoneUsbUpstream.resolve().
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from rootfs.app.networkmanager import LEASE_OWNER, NetworkManagerResult
from test_support.iphone_usb_fixtures import (
    FakeNetworkManager,
    IPhoneUsbUpstreamHarness,
    usb_upstream,
)
from test_support.process import FakeProcess
from test_support.runner import FakeRunner


class IPhoneUsbPairingTests(IPhoneUsbUpstreamHarness):
    def test_phone_absence_does_not_prepare_profile_or_start_helper(self) -> None:
        processes: list[FakeProcess] = []
        network_manager = FakeNetworkManager()
        manager = self._manager(
            FakeRunner(),
            network_manager,
            popen=lambda *args, **kwargs: (
                processes.append(FakeProcess()) or processes[-1]
            ),
        )

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(network_manager.inspect_calls, [])
        self.assertEqual(processes, [])
        self.assertEqual(manager.pairing_state, "waiting_for_device")

    def test_active_profile_resolves_upstream(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        network_manager = FakeNetworkManager(
            [NetworkManagerResult(usb_upstream(), "active", None, True)]
        )
        manager = self._manager(runner, network_manager)

        upstream, errors = manager.resolve()

        self.assertEqual(errors, [])
        assert upstream is not None
        self.assertEqual(upstream.interface, "eth0")
        self.assertEqual(manager.pairing_state, "paired")
        self.assertTrue(manager.runtime_status()["upstream_carrier"])
        self.assertEqual(network_manager.inspect_calls, ["eth0"])
        self.assertEqual(
            manager.runtime_status()["upstream_lease_owner"],
            LEASE_OWNER,
        )

    def test_pairing_is_still_required(self) -> None:
        runner = FakeRunner()
        runner.usb.idevice_udids = ["iphone-udid"]
        self._add_apple_usb_device()
        manager = self._manager(runner, FakeNetworkManager())

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertIn("tap Trust", errors[0])
        self.assertEqual(manager.pairing_state, "waiting_for_trust")

    def test_missing_carrier_waits_for_personal_hotspot_without_nm_retry(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0", carrier=False)
        network_manager = FakeNetworkManager()
        manager = self._manager(runner, network_manager)

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(manager.pairing_state, "waiting_for_hotspot")
        self.assertFalse(manager.runtime_status()["upstream_carrier"])
        self.assertIn("Allow Others to Join", errors[0])
        self.assertEqual(network_manager.inspect_calls, [])

    def test_unreadable_carrier_proceeds_to_networkmanager(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0", carrier=None)
        network_manager = FakeNetworkManager(
            [NetworkManagerResult(usb_upstream(), "active", None, True)]
        )
        manager = self._manager(runner, network_manager)

        upstream, errors = manager.resolve()

        self.assertEqual(errors, [])
        self.assertEqual(upstream, usb_upstream())
        self.assertEqual(network_manager.inspect_calls, ["eth0"])

    def test_pairing_prompt_is_rate_limited(self) -> None:
        runner = FakeRunner()
        runner.usb.idevice_udids = ["iphone-udid"]
        self._add_apple_usb_device()
        manager = self._manager(runner, FakeNetworkManager())

        with patch(
            "rootfs.app.upstream_iphone_runtime.time.monotonic",
            side_effect=[100.0, 105.0, 161.0],
        ):
            manager.resolve()
            manager.resolve()
            pair_commands = [c for c in runner.commands if c[-1:] == ["pair"]]
            self.assertEqual(len(pair_commands), 1)

            manager.resolve()
            pair_commands = [c for c in runner.commands if c[-1:] == ["pair"]]
            self.assertEqual(len(pair_commands), 2)

    def test_multiple_devices_block_fallback(self) -> None:
        runner = FakeRunner()
        runner.usb.idevice_udids = ["one", "two"]
        self._add_apple_usb_device()
        manager = self._manager(runner, FakeNetworkManager())

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(manager.pairing_state, "multiple_devices")
        self.assertFalse(manager.fallback_allowed())

    def test_multiple_ipheth_interfaces_block_fallback(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        self._add_ipheth_interface("eth1")
        manager = self._manager(runner, FakeNetworkManager())

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(manager.pairing_state, "multiple_devices")
        self.assertFalse(manager.fallback_allowed())

    def test_profile_conflict_blocks_fallback(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        network_manager = FakeNetworkManager(
            [NetworkManagerResult(None, "foreign", "foreign profile", False)]
        )
        manager = self._manager(runner, network_manager)

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(manager.pairing_state, "profile_conflict")
        self.assertFalse(manager.fallback_allowed())

    def test_invalid_lease_blocks_fallback(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        network_manager = FakeNetworkManager(
            [NetworkManagerResult(None, "invalid", "bad lease", False)]
        )
        manager = self._manager(runner, network_manager)

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(manager.pairing_state, "invalid_lease")
        self.assertFalse(manager.fallback_allowed())

    def test_waiting_profile_allows_fallback(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        network_manager = FakeNetworkManager(
            [NetworkManagerResult(None, "waiting", "waiting", True)]
        )
        manager = self._manager(runner, network_manager)

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(manager.pairing_state, "waiting_for_profile")
        self.assertTrue(manager.fallback_allowed())

    def test_driver_inactive_message_when_no_interface(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        manager = self._manager(runner, FakeNetworkManager())
        manager.runtime.ipheth_driver_active = lambda: False

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(manager.pairing_state, "waiting_for_interface")
        self.assertIn("ipheth driver is not active", errors[0])


if __name__ == "__main__":
    unittest.main()
