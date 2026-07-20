"""Shared fixtures for IPhoneUsbUpstream test suites."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rootfs.app.const import IPHONE_USB
from rootfs.app.networkmanager import NetworkManagerResult
from rootfs.app.upstream_iphone import IPhoneUsbUpstream
from rootfs.app.upstream_models import ResolvedUpstream

from .engine_fixtures import make_config
from .process import FakeProcess
from .runner import FakeRunner


def usb_upstream(interface: str = "eth0") -> ResolvedUpstream:
    return ResolvedUpstream(
        connection=IPHONE_USB,
        interface=interface,
        address="172.20.10.2/28",
        gateway="172.20.10.1",
    )


class FakeNetworkManager:
    def __init__(
        self,
        results: list[NetworkManagerResult] | None = None,
    ) -> None:
        self.results = list(results or [])
        self.inspect_calls: list[str] = []
        self.default = NetworkManagerResult(None, "waiting", "waiting", True)
        self.continuous = True
        self.inspect_error: Exception | None = None

    def inspect(
        self,
        interface: str,
        management: object = None,
    ) -> NetworkManagerResult:
        self.inspect_calls.append(interface)
        if self.inspect_error is not None:
            raise self.inspect_error
        if self.results:
            return self.results.pop(0)
        return self.default

    def continuity(self, upstream: ResolvedUpstream) -> bool:
        return self.continuous


class IPhoneUsbUpstreamHarness(unittest.TestCase):
    """Common device/filesystem scaffolding for IPhoneUsbUpstream tests."""

    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.run_dir = self.root / "run"
        self.usb_root = self.root / "dev" / "bus" / "usb"
        self.sys_net_root = self.root / "sys" / "class" / "net"
        self.sys_usb_root = self.root / "sys" / "bus" / "usb" / "devices"
        self.driver_root = self.root / "drivers"
        for path in (
            self.usb_root,
            self.sys_net_root,
            self.sys_usb_root,
            self.driver_root,
        ):
            path.mkdir(parents=True)
        self.clock = [1000.0]

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _tick(self) -> float:
        return self.clock[0]

    def _manager(
        self,
        runner: FakeRunner,
        network_manager: FakeNetworkManager,
        *,
        popen=None,
    ) -> IPhoneUsbUpstream:
        return IPhoneUsbUpstream(
            make_config(mobile_connection=IPHONE_USB),
            lambda *args, **kwargs: runner.run(list(args), **kwargs),
            run_dir=self.run_dir,
            lockdown_dir=self.root / "lockdown",
            usb_root=self.usb_root,
            sys_net_root=self.sys_net_root,
            sys_usb_root=self.sys_usb_root,
            which=lambda command: f"/usr/bin/{command}",
            popen=popen or (lambda *args, **kwargs: FakeProcess()),
            network_manager=network_manager,
            monotonic=self._tick,
        )

    def _add_ipheth_interface(
        self,
        name: str = "eth0",
        *,
        carrier: bool | None = True,
    ) -> None:
        target = self.driver_root / "ipheth"
        target.mkdir(exist_ok=True)
        interface = self.sys_net_root / name / "device"
        interface.mkdir(parents=True)
        (interface / "driver").symlink_to(target)
        if carrier is not None:
            (self.sys_net_root / name / "carrier").write_text(
                "1\n" if carrier else "0\n",
                encoding="utf-8",
            )

    def _add_apple_usb_device(self, name: str = "1-1") -> None:
        device = self.sys_usb_root / name
        device.mkdir(parents=True)
        (device / "idVendor").write_text("05ac\n", encoding="utf-8")

    def _paired_runner(self) -> FakeRunner:
        runner = FakeRunner()
        runner.usb.idevice_udids = ["iphone-udid"]
        runner.usb.idevice_paired_udids = ["iphone-udid"]
        runner.usb.idevice_validate_result.returncode = 0
        return runner
