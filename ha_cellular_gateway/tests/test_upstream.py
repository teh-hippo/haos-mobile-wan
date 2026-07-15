import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import FakeProcess, FakeRunner, make_config
from rootfs.app.upstream_iphone import IPhoneUsbUpstream


class IPhoneUsbUpstreamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.run_dir = self.root / "run"
        self.lockdown_dir = self.root / "lockdown"
        self.usb_root = self.root / "dev" / "bus" / "usb"
        self.sys_net_root = self.root / "sys" / "class" / "net"
        self.sys_usb_root = self.root / "sys" / "bus" / "usb" / "devices"
        self.driver_root = self.root / "drivers"
        self.udhcpc_script = self.root / "udhcpc.script"
        self.usb_root.mkdir(parents=True)
        self.sys_net_root.mkdir(parents=True)
        self.sys_usb_root.mkdir(parents=True)
        self.driver_root.mkdir(parents=True)
        self.udhcpc_script.write_text("#!/bin/sh\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _manager(
        self,
        runner: FakeRunner,
        *,
        popen=None,
    ) -> IPhoneUsbUpstream:
        return IPhoneUsbUpstream(
            make_config(upstream_mode="iphone_usb"),
            lambda *args, **kwargs: runner.run(list(args), **kwargs),
            run_dir=self.run_dir,
            lockdown_dir=self.lockdown_dir,
            usb_root=self.usb_root,
            sys_net_root=self.sys_net_root,
            sys_usb_root=self.sys_usb_root,
            udhcpc_script=self.udhcpc_script,
            which=lambda command: f"/usr/bin/{command}",
            popen=popen or (lambda *args, **kwargs: FakeProcess()),
        )

    def _add_ipheth_interface(self, name: str = "eth0") -> None:
        target = self.driver_root / "ipheth"
        target.mkdir(exist_ok=True)
        interface = self.sys_net_root / name / "device"
        interface.mkdir(parents=True)
        (interface / "driver").symlink_to(target)

    def _add_apple_usb_device(self, name: str = "1-1") -> None:
        device = self.sys_usb_root / name
        device.mkdir(parents=True)
        (device / "idVendor").write_text("05ac\n", encoding="utf-8")

    def _write_app_lease(
        self,
        interface: str,
        address: str,
        gateway: str,
    ) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "iphone-usb-lease.json").write_text(
            json.dumps(
                {
                    "owner": "app",
                    "interface": interface,
                    "address": address,
                    "gateway": gateway,
                }
            ),
            encoding="utf-8",
        )

    def test_resolve_usb_upstream_uses_app_owned_lease(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        runner.idevice_validate_result.returncode = 0
        self._add_ipheth_interface()
        self._add_apple_usb_device()

        def popen(args, **kwargs):
            if args[0] == "udhcpc":
                self._write_app_lease("eth0", "172.20.10.2/28", "172.20.10.1")
            return FakeProcess()

        upstream, errors = self._manager(runner, popen=popen).resolve(allow_mutation=True)

        self.assertEqual(errors, [])
        assert upstream is not None
        self.assertEqual(upstream.interface, "eth0")
        self.assertEqual(upstream.address, "172.20.10.2/28")
        self.assertEqual(upstream.gateway, "172.20.10.1")

    def test_pairing_guidance_fails_closed(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        self._add_apple_usb_device()

        upstream, errors = self._manager(runner).resolve(allow_mutation=True)

        self.assertIsNone(upstream)
        self.assertEqual(len(errors), 1)
        self.assertIn("tap Trust", errors[0])

    def test_dry_run_external_lease_is_not_flushed_on_cleanup(self) -> None:
        runner = FakeRunner()
        runner.interface_addresses["eth0"] = ("172.20.10.2", 28)
        runner.main_default_routes.append(
            {"dst": "default", "gateway": "172.20.10.1", "dev": "eth0"}
        )
        self._add_ipheth_interface()
        self._add_apple_usb_device()
        upstream = self._manager(runner)

        resolved, errors = upstream.resolve(allow_mutation=False)

        self.assertEqual(errors, [])
        self.assertIsNotNone(resolved)
        upstream.cleanup()
        self.assertFalse(
            any(
                command[:4] == ["ip", "-4", "address", "flush"]
                or command[:5] == ["ip", "route", "del", "default", "dev"]
                for command in runner.commands
            )
        )

    def test_rejects_host_managed_conflict_when_mutating(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        runner.idevice_validate_result.returncode = 0
        runner.interface_addresses["eth0"] = ("172.20.10.2", 28)
        runner.main_default_routes.append(
            {"dst": "default", "gateway": "172.20.10.1", "dev": "eth0"}
        )
        self._add_ipheth_interface()
        self._add_apple_usb_device()

        upstream, errors = self._manager(runner).resolve(allow_mutation=True)

        self.assertIsNone(upstream)
        self.assertEqual(
            errors,
            [
                "iPhone USB interface is already host-managed; leave ipheth unmanaged so the app can own DHCP and the main default route"
            ],
        )

    def test_rejects_invalid_dynamic_lease(self) -> None:
        runner = FakeRunner()
        runner.interface_addresses["eth0"] = ("172.20.10.0", 28)
        runner.main_default_routes.append(
            {"dst": "default", "gateway": "172.20.10.1", "dev": "eth0"}
        )
        self._add_ipheth_interface()

        upstream, errors = self._manager(runner).resolve(allow_mutation=False)

        self.assertIsNone(upstream)
        self.assertEqual(errors, ["iPhone USB lease address is not a usable host address"])

    def test_rejects_overlapping_dynamic_lease(self) -> None:
        runner = FakeRunner()
        runner.interface_addresses["eth0"] = ("192.168.1.20", 24)
        runner.main_default_routes.append(
            {"dst": "default", "gateway": "192.168.1.1", "dev": "eth0"}
        )
        self._add_ipheth_interface()

        upstream, errors = self._manager(runner).resolve(allow_mutation=False)

        self.assertIsNone(upstream)
        self.assertEqual(errors, ["iPhone USB lease overlaps the management network"])

    def test_usbmuxd_startup_failure_surfaces_output(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
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
            popen=popen,
        ).resolve(allow_mutation=True)

        self.assertIsNone(upstream)
        self.assertEqual(
            errors,
            ["usbmuxd failed to start: socket bind failed; permission denied"],
        )

    def test_usbmuxd_running_process_uses_log_file_not_pipes(self) -> None:
        runner = FakeRunner()
        self._add_apple_usb_device()
        self._add_ipheth_interface()
        captured: dict[str, object] = {}

        def popen(*args, **kwargs):
            captured["stdout"] = kwargs["stdout"]
            captured["stderr"] = kwargs["stderr"]
            kwargs["stdout"].write("x" * 131072)
            kwargs["stdout"].flush()
            return FakeProcess()

        manager = self._manager(runner, popen=popen)
        manager._ipheth_driver_active = lambda: True

        upstream, errors = manager.resolve(allow_mutation=True)

        self.assertIsNone(upstream)
        self.assertEqual(
            errors,
            ["Connect a single trusted iPhone with Personal Hotspot enabled"],
        )
        self.assertIs(captured["stdout"], captured["stderr"])
        self.assertNotEqual(captured["stdout"], subprocess.PIPE)
        self.assertGreaterEqual(
            len(manager.runtime.usbmuxd_log.read_text(encoding="utf-8")),
            131072,
        )

    def test_usbmuxd_delayed_early_exit_surfaces_output(self) -> None:
        runner = FakeRunner()
        self._add_apple_usb_device()

        class DelayedExitProcess(FakeProcess):
            def wait(self, timeout: int = 5) -> int:
                self.running = False
                return self.returncode

        def popen(*args, **kwargs):
            kwargs["stdout"].write("late startup failure\n")
            kwargs["stdout"].flush()
            return DelayedExitProcess(returncode=1)

        upstream, errors = self._manager(runner, popen=popen).resolve(allow_mutation=True)

        self.assertIsNone(upstream)
        self.assertEqual(errors, ["usbmuxd failed to start: late startup failure"])

    def test_disconnect_and_reconnect_updates_interface_and_address(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        runner.idevice_validate_result.returncode = 0
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        processes: list[FakeProcess] = []

        def popen(args, **kwargs):
            if args[0] == "udhcpc":
                interface = args[3]
                if interface == "eth0":
                    self._write_app_lease("eth0", "172.20.10.2/28", "172.20.10.1")
                else:
                    self._write_app_lease("eth1", "172.20.10.6/28", "172.20.10.1")
            process = FakeProcess()
            processes.append(process)
            return process

        manager = self._manager(runner, popen=popen)
        first, errors = manager.resolve(allow_mutation=True)
        self.assertEqual(errors, [])
        assert first is not None
        self.assertEqual(first.interface, "eth0")

        shutil.rmtree(self.sys_net_root / "eth0")
        runner.commands.clear()
        (self.run_dir / "iphone-usb-lease.json").unlink()
        self._add_ipheth_interface("eth1")
        second, errors = manager.resolve(allow_mutation=True)

        self.assertEqual(errors, [])
        assert second is not None
        self.assertEqual(second.interface, "eth1")
        self.assertEqual(second.address, "172.20.10.6/28")
        self.assertFalse(processes[1].running)

    def test_exited_dhcp_process_is_restarted(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        runner.idevice_validate_result.returncode = 0
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        processes: list[FakeProcess] = []

        def popen(args, **kwargs):
            if args[0] == "udhcpc":
                self._write_app_lease("eth0", "172.20.10.2/28", "172.20.10.1")
            process = FakeProcess()
            processes.append(process)
            return process

        manager = self._manager(runner, popen=popen)
        upstream, errors = manager.resolve(allow_mutation=True)
        self.assertEqual(errors, [])
        self.assertIsNotNone(upstream)

        processes[-1].running = False
        upstream, errors = manager.resolve(allow_mutation=True)

        self.assertEqual(errors, [])
        self.assertIsNotNone(upstream)
        self.assertEqual(len(processes), 3)
        self.assertTrue(processes[-1].running)


if __name__ == "__main__":
    unittest.main()
