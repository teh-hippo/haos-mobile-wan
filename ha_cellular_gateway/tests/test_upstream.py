import tempfile
import unittest
from pathlib import Path

from helpers import FakeProcess, FakeRunner, make_config
from rootfs.app.upstream import IPhoneUsbUpstream


class IPhoneUsbUpstreamTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.run_dir = self.root / "run"
        self.lockdown_dir = self.root / "lockdown"
        self.usb_root = self.root / "dev" / "bus" / "usb"
        self.udev_root = self.root / "run" / "udev"
        self.sys_net_root = self.root / "sys" / "class" / "net"
        self.sys_usb_root = self.root / "sys" / "bus" / "usb" / "devices"
        self.driver_root = self.root / "drivers"
        self.udhcpc_script = self.root / "udhcpc.script"
        self.usb_root.mkdir(parents=True)
        self.udev_root.mkdir(parents=True)
        self.sys_net_root.mkdir(parents=True)
        self.sys_usb_root.mkdir(parents=True)
        self.driver_root.mkdir(parents=True)
        self.udhcpc_script.write_text("#!/bin/sh\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _manager(self, runner: FakeRunner) -> IPhoneUsbUpstream:
        return IPhoneUsbUpstream(
            make_config(upstream_mode="iphone_usb"),
            lambda *args, **kwargs: runner.run(list(args), **kwargs),
            run_dir=self.run_dir,
            lockdown_dir=self.lockdown_dir,
            usb_root=self.usb_root,
            udev_root=self.udev_root,
            sys_net_root=self.sys_net_root,
            sys_usb_root=self.sys_usb_root,
            udhcpc_script=self.udhcpc_script,
            which=lambda command: f"/usr/bin/{command}",
            popen=lambda *args, **kwargs: FakeProcess(),
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

    def test_resolve_usb_upstream_captures_lease_and_strips_default_route(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        runner.idevice_validate_result.returncode = 0
        runner.interface_addresses["eth0"] = ("172.20.10.2", 28)
        runner.main_default_routes = [
            {"dst": "default", "gateway": "192.168.1.1", "dev": "end0"},
            {"dst": "default", "gateway": "172.20.10.1", "dev": "eth0"},
        ]
        self._add_ipheth_interface()
        self._add_apple_usb_device()

        upstream, errors = self._manager(runner).resolve(allow_mutation=True)

        self.assertEqual(errors, [])
        assert upstream is not None
        self.assertEqual(upstream.interface, "eth0")
        self.assertEqual(upstream.address, "172.20.10.2/28")
        self.assertEqual(upstream.gateway, "172.20.10.1")
        self.assertEqual(runner.main_default_routes, [{"dst": "default", "gateway": "192.168.1.1", "dev": "end0"}])

    def test_pairing_guidance_fails_closed(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        self._add_apple_usb_device()

        upstream, errors = self._manager(runner).resolve(allow_mutation=True)

        self.assertIsNone(upstream)
        self.assertEqual(len(errors), 1)
        self.assertIn("tap Trust", errors[0])


if __name__ == "__main__":
    unittest.main()
