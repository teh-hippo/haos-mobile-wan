from __future__ import annotations

import unittest

from rootfs.app.const import IPHONE_USB
from rootfs.app.networkmanager import NetworkManagerResult
from rootfs.app.upstream_iphone import IPhoneUsbUpstream
from test_support.engine_fixtures import make_config
from test_support.iphone_usb_fixtures import (
    FakeNetworkManager,
    IPhoneUsbUpstreamHarness,
    usb_upstream,
)
from test_support.process import FakeProcess
from test_support.runner import FakeRunner


class IPhoneUsbHelperProcessTests(IPhoneUsbUpstreamHarness):
    def test_reports_networkmanager_lease_owner(self) -> None:
        manager = self._manager(FakeRunner(), FakeNetworkManager())
        self.assertEqual(
            manager.runtime_status()["upstream_lease_owner"],
            None,
        )

    def test_missing_nmcli_is_a_capability_error(self) -> None:
        runner = self._paired_runner()
        manager = IPhoneUsbUpstream(
            make_config(mobile_connection=IPHONE_USB),
            lambda *args, **kwargs: runner.run(list(args), **kwargs),
            run_dir=self.run_dir,
            lockdown_dir=self.root / "lockdown",
            usb_root=self.usb_root,
            sys_net_root=self.sys_net_root,
            sys_usb_root=self.sys_usb_root,
            which=lambda command: None if command == "nmcli" else f"/usr/bin/{command}",
            popen=lambda *args, **kwargs: FakeProcess(),
            network_manager=FakeNetworkManager(),
        )

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertIn("Required command is unavailable: nmcli", errors)

    def test_cleanup_does_not_mutate_networkmanager_state(self) -> None:
        runner = self._paired_runner()
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        network_manager = FakeNetworkManager(
            [NetworkManagerResult(usb_upstream(), "active", None, True)]
        )
        manager = self._manager(runner, network_manager)
        manager.resolve()
        runner.commands.clear()

        manager.cleanup()

        self.assertFalse(
            any(
                command[:4] == ["ip", "-4", "address", "del"]
                or command[:1] == ["nmcli"]
                for command in runner.commands
            )
        )

    def test_usbmuxd_startup_failure_surfaces_output(self) -> None:
        runner = FakeRunner()
        runner.usb.idevice_udids = ["iphone-udid"]
        self._add_ipheth_interface()
        self._add_apple_usb_device()

        def popen(*args, **kwargs):
            kwargs["stdout"].write("socket bind failed\n")
            kwargs["stdout"].flush()
            kwargs["stderr"].write("permission denied\n")
            kwargs["stderr"].flush()
            return FakeProcess(running=False, returncode=1)

        upstream, errors = self._manager(
            runner,
            FakeNetworkManager(),
            popen=popen,
        ).resolve()

        self.assertIsNone(upstream)
        self.assertEqual(
            errors,
            ["usbmuxd failed to start: socket bind failed; permission denied"],
        )


if __name__ == "__main__":
    unittest.main()
