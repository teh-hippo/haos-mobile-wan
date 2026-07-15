import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from helpers import FakeProcess, FakeRunner, Result, make_config
from rootfs.app.const import IPHONE_USB
from rootfs.app.errors import GatewayError
from rootfs.app.upstream_iphone import IPhoneUsbUpstream
from rootfs.app.upstream_iphone_resolver import LeaseResolution
from rootfs.app.upstream_models import ResolvedUpstream


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
            make_config(mobile_connection=IPHONE_USB),
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
        runner: FakeRunner,
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
        ip, prefix = address.rsplit("/", 1)
        runner.interface_addresses[interface] = (ip, int(prefix))

    def test_resolve_usb_upstream_uses_app_owned_lease(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        runner.idevice_paired_udids = ["iphone-udid"]
        runner.idevice_validate_result.returncode = 0
        self._add_ipheth_interface()
        self._add_apple_usb_device()

        def popen(args, **kwargs):
            if args[0] == "udhcpc":
                self._write_app_lease(
                    runner,
                    "eth0",
                    "172.20.10.2/28",
                    "172.20.10.1",
                )
            return FakeProcess()

        upstream, errors = self._manager(runner, popen=popen).resolve()

        self.assertEqual(errors, [])
        assert upstream is not None
        self.assertEqual(upstream.interface, "eth0")
        self.assertEqual(upstream.address, "172.20.10.2/28")
        self.assertEqual(upstream.gateway, "172.20.10.1")
        self.assertEqual(upstream.connection, IPHONE_USB)

    def test_pairing_guidance_fails_closed(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        self._add_apple_usb_device()

        manager = self._manager(runner)
        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(len(errors), 1)
        self.assertIn("tap Trust", errors[0])

    def test_pairing_prompt_is_rate_limited(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        self._add_apple_usb_device()
        manager = self._manager(runner)

        with patch(
            "rootfs.app.upstream_iphone_runtime.time.monotonic",
            side_effect=[100.0, 105.0, 161.0],
        ):
            manager.resolve()
            manager.resolve()
            pair_commands = [
                command for command in runner.commands if command[-1:] == ["pair"]
            ]
            self.assertEqual(len(pair_commands), 1)
            self.assertFalse(
                any(command[-1:] == ["validate"] for command in runner.commands)
            )

            manager.resolve()
            pair_commands = [
                command for command in runner.commands if command[-1:] == ["pair"]
            ]
            self.assertEqual(len(pair_commands), 2)

    def test_external_lease_is_not_flushed_on_cleanup(self) -> None:
        runner = FakeRunner()
        runner.interface_addresses["eth0"] = ("172.20.10.2", 28)
        runner.main_default_routes.append(
            {"dst": "default", "gateway": "172.20.10.1", "dev": "eth0"}
        )
        self._add_ipheth_interface()
        self._add_apple_usb_device()
        upstream = self._manager(runner)

        upstream.cleanup()
        self.assertFalse(
            any(
                command[:4] == ["ip", "-4", "address", "del"]
                or command[:5] == ["ip", "route", "del", "default", "dev"]
                for command in runner.commands
            )
        )

    def test_rejects_host_managed_conflict_when_mutating(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        runner.idevice_paired_udids = ["iphone-udid"]
        runner.idevice_validate_result.returncode = 0
        runner.interface_addresses["eth0"] = ("172.20.10.2", 28)
        runner.main_default_routes.append(
            {"dst": "default", "gateway": "172.20.10.1", "dev": "eth0"}
        )
        self._add_ipheth_interface()
        self._add_apple_usb_device()

        manager = self._manager(runner)
        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(
            errors,
            [
                "iPhone USB interface is already host-managed; leave ipheth unmanaged so the app can own DHCP and the main default route"
            ],
        )
        self.assertFalse(manager.fallback_safe)

    def test_host_managed_usb_blocks_fallback_without_detected_phone(self) -> None:
        runner = FakeRunner()
        runner.interface_addresses["eth0"] = ("172.20.10.2", 28)
        self._add_ipheth_interface()
        self._add_apple_usb_device()
        manager = self._manager(runner)

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(errors, [manager.HOST_CONFLICT_MESSAGE])
        self.assertFalse(manager.fallback_allowed())

    def test_mixed_usb_addresses_block_fallback_and_preserve_host_address(
        self,
    ) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        runner.idevice_paired_udids = ["iphone-udid"]
        runner.idevice_validate_result.returncode = 0
        self._add_ipheth_interface()
        self._add_apple_usb_device()
        self._write_app_lease(
            runner,
            "eth0",
            "172.20.10.2/28",
            "172.20.10.1",
        )
        runner.interface_addresses["eth0"] = [
            ("172.20.10.2", 28),
            ("192.168.1.20", 24),
        ]
        manager = self._manager(runner)

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(errors, [manager.HOST_CONFLICT_MESSAGE])
        self.assertFalse(manager.fallback_allowed())

        manager.cleanup()

        self.assertEqual(
            runner.interface_addresses["eth0"],
            ("192.168.1.20", 24),
        )
        self.assertFalse((self.run_dir / "iphone-usb-lease.json").exists())

    def test_external_lease_owner_is_never_accepted(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        runner.idevice_paired_udids = ["iphone-udid"]
        runner.idevice_validate_result.returncode = 0
        self._add_ipheth_interface()
        self._add_apple_usb_device()
        manager = self._manager(runner)
        manager._resolved_interface = lambda interface: LeaseResolution(
            ResolvedUpstream(
                connection=IPHONE_USB,
                interface=interface,
                address="172.20.10.2/28",
                gateway="172.20.10.1",
            ),
            None,
            "external",
        )

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(errors, [manager.HOST_CONFLICT_MESSAGE])
        self.assertFalse(manager.fallback_allowed())

    def test_rejects_invalid_dynamic_lease(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        runner.idevice_paired_udids = ["iphone-udid"]
        runner.idevice_validate_result.returncode = 0
        self._add_apple_usb_device()
        self._add_ipheth_interface()
        self._write_app_lease(
            runner,
            "eth0",
            "172.20.10.0/28",
            "172.20.10.1",
        )

        upstream, errors = self._manager(runner).resolve()

        self.assertIsNone(upstream)
        self.assertEqual(errors, ["iPhone USB lease address is not a usable host address"])
        self.assertFalse((self.run_dir / "iphone-usb-lease.json").exists())

    def test_rejects_overlapping_dynamic_lease(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        runner.idevice_paired_udids = ["iphone-udid"]
        runner.idevice_validate_result.returncode = 0
        self._add_apple_usb_device()
        self._add_ipheth_interface()
        self._write_app_lease(
            runner,
            "eth0",
            "192.168.1.20/24",
            "192.168.1.1",
        )

        upstream, errors = self._manager(runner).resolve()

        self.assertIsNone(upstream)
        self.assertEqual(errors, ["iPhone USB lease overlaps the management network"])
        self.assertFalse((self.run_dir / "iphone-usb-lease.json").exists())

    def test_failed_invalid_lease_cleanup_blocks_fallback(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        runner.idevice_paired_udids = ["iphone-udid"]
        runner.idevice_validate_result.returncode = 0
        self._add_apple_usb_device()
        self._add_ipheth_interface()
        self._write_app_lease(
            runner,
            "eth0",
            "192.168.1.20/24",
            "192.168.1.1",
        )
        manager = self._manager(runner)
        original_run = manager.run

        def fail_cleanup(*args, **kwargs):
            if args[:4] == ("ip", "-4", "address", "del"):
                return Result(returncode=1)
            return original_run(*args, **kwargs)

        manager.run = fail_cleanup

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertIn("cleanup failed", errors[0])
        self.assertFalse(manager.fallback_allowed())
        self.assertTrue((self.run_dir / "iphone-usb-lease.json").exists())
        self.assertIn("eth0", runner.interface_addresses)

    def test_cleanup_uses_recorded_interface_when_discovery_is_unavailable(
        self,
    ) -> None:
        runner = FakeRunner()
        self._add_ipheth_interface()
        self._write_app_lease(
            runner,
            "eth0",
            "172.20.10.2/28",
            "172.20.10.1",
        )
        manager = self._manager(runner)
        manager.interface = None

        manager.cleanup()

        self.assertNotIn("eth0", runner.interface_addresses)
        self.assertFalse((self.run_dir / "iphone-usb-lease.json").exists())

    def test_invalid_lease_record_is_retained(self) -> None:
        runner = FakeRunner()
        self.run_dir.mkdir(parents=True)
        lease_path = self.run_dir / "iphone-usb-lease.json"
        lease_path.write_text("{}", encoding="utf-8")
        manager = self._manager(runner)

        with self.assertRaisesRegex(GatewayError, "lease record is invalid"):
            manager.cleanup()

        self.assertTrue(lease_path.exists())

    def test_stale_app_lease_is_discarded(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        runner.idevice_paired_udids = ["iphone-udid"]
        runner.idevice_validate_result.returncode = 0
        self._add_apple_usb_device()
        self._add_ipheth_interface()
        self._write_app_lease(
            runner,
            "eth0",
            "172.20.10.2/28",
            "172.20.10.1",
        )
        runner.interface_addresses.pop("eth0")
        manager = self._manager(runner)

        upstream, errors = manager.resolve()

        self.assertIsNone(upstream)
        self.assertEqual(errors, ["iPhone USB lease is stale"])
        self.assertEqual(manager.pairing_state, "waiting_for_dhcp")
        self.assertTrue(manager.fallback_safe)
        self.assertFalse((self.run_dir / "iphone-usb-lease.json").exists())

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
        ).resolve()

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

        upstream, errors = manager.resolve()

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

        upstream, errors = self._manager(runner, popen=popen).resolve()

        self.assertIsNone(upstream)
        self.assertEqual(errors, ["usbmuxd failed to start: late startup failure"])

    def test_disconnect_and_reconnect_updates_interface_and_address(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        runner.idevice_paired_udids = ["iphone-udid"]
        runner.idevice_validate_result.returncode = 0
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        processes: list[FakeProcess] = []

        def popen(args, **kwargs):
            if args[0] == "udhcpc":
                interface = args[3]
                if interface == "eth0":
                    self._write_app_lease(
                        runner,
                        "eth0",
                        "172.20.10.2/28",
                        "172.20.10.1",
                    )
                else:
                    self._write_app_lease(
                        runner,
                        "eth1",
                        "172.20.10.6/28",
                        "172.20.10.1",
                    )
            process = FakeProcess()
            processes.append(process)
            return process

        manager = self._manager(runner, popen=popen)
        first, errors = manager.resolve()
        self.assertEqual(errors, [])
        assert first is not None
        self.assertEqual(first.interface, "eth0")

        shutil.rmtree(self.sys_net_root / "eth0")
        runner.commands.clear()
        (self.run_dir / "iphone-usb-lease.json").unlink()
        self._add_ipheth_interface("eth1")
        second, errors = manager.resolve()

        self.assertEqual(errors, [])
        assert second is not None
        self.assertEqual(second.interface, "eth1")
        self.assertEqual(second.address, "172.20.10.6/28")
        self.assertFalse(processes[1].running)

    def test_exited_dhcp_process_is_restarted(self) -> None:
        runner = FakeRunner()
        runner.idevice_udids = ["iphone-udid"]
        runner.idevice_paired_udids = ["iphone-udid"]
        runner.idevice_validate_result.returncode = 0
        self._add_apple_usb_device()
        self._add_ipheth_interface("eth0")
        processes: list[FakeProcess] = []

        def popen(args, **kwargs):
            if args[0] == "udhcpc":
                self._write_app_lease(
                    runner,
                    "eth0",
                    "172.20.10.2/28",
                    "172.20.10.1",
                )
            process = FakeProcess()
            processes.append(process)
            return process

        manager = self._manager(runner, popen=popen)
        upstream, errors = manager.resolve()
        self.assertEqual(errors, [])
        self.assertIsNotNone(upstream)

        processes[-1].running = False
        upstream, errors = manager.resolve()

        self.assertEqual(errors, [])
        self.assertIsNotNone(upstream)
        self.assertEqual(len(processes), 3)
        self.assertTrue(processes[-1].running)


if __name__ == "__main__":
    unittest.main()
