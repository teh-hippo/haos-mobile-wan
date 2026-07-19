from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from .command import RunCommand
from .config import RUN_DIR, GatewayConfig
from .errors import GatewayError
from .networkmanager import NetworkManagerIphone
from .upstream_iphone_runtime import IPhoneUsbRuntime
from .upstream_usb import UpstreamResolution, UsbNetworkUpstream

if TYPE_CHECKING:
    from .management import ManagementBaseline

class IPhoneUsbUpstream(UsbNetworkUpstream):
    def __init__(
        self,
        config: GatewayConfig,
        run: RunCommand,
        *,
        run_dir: Path = RUN_DIR,
        lockdown_dir: Path = Path("/data/lockdown"),
        usb_root: Path = Path("/dev/bus/usb"),
        sys_net_root: Path = Path("/sys/class/net"),
        sys_usb_root: Path = Path("/sys/bus/usb/devices"),
        popen: Callable[..., subprocess.Popen[str]] | None = None,
        which: Callable[[str], str | None] | None = None,
        network_manager: NetworkManagerIphone | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.runtime = IPhoneUsbRuntime(
            run,
            run_dir=run_dir,
            lockdown_dir=lockdown_dir,
            usb_root=usb_root,
            sys_net_root=sys_net_root,
            sys_usb_root=sys_usb_root,
            popen=popen,
            which=which,
        )
        super().__init__(
            run,
            network_manager
            or NetworkManagerIphone(config, run, monotonic=monotonic),
            label="iPhone USB",
            ready_state="paired",
            monotonic=monotonic,
        )
        self.device_udid: str | None = None

    def runtime_status(self) -> dict[str, object]:
        status = super().runtime_status()
        status["upstream_device_udid"] = self.device_udid
        status["upstream_lockdown_path"] = str(self.runtime.lockdown_dir)
        return status

    def resolve(
        self,
        management: ManagementBaseline | None = None,
        downstream_interface: str | None = None,
    ) -> UpstreamResolution:
        del downstream_interface
        self._begin()

        errors = self.runtime.capability_errors()
        if errors:
            self._forget_lease()
            return None, errors

        apple_present = self.runtime.apple_usb_present()
        if not apple_present:
            self._forget_lease()
            return self._fail(
                "waiting_for_device",
                "Connect a single trusted iPhone with Personal Hotspot enabled",
            )

        try:
            self.runtime.ensure_usbmuxd()
        except GatewayError as err:
            self._forget_lease()
            return self._fail("daemon_failed", str(err))

        udids = self.runtime.connected_udids()
        if not udids:
            self._forget_lease()
            if apple_present and not self.runtime.ipheth_driver_active():
                message = (
                    "Apple USB device is present but the host ipheth driver "
                    "is not active"
                )
            else:
                message = "Connect a single trusted iPhone with Personal Hotspot enabled"
            return self._fail("waiting_for_device", message)
        if len(udids) > 1:
            self._forget_lease()
            return self._fail(
                "multiple_devices",
                "Connect only one iPhone USB upstream at a time",
                safe=False,
            )

        udid = udids[0]
        self.device_udid = udid
        if not self.runtime.validate_pairing(udid):
            pairing = self.runtime.pair_device(udid)
            if not pairing.paired:
                self._forget_lease()
                assert pairing.message is not None
                return self._fail(pairing.state, pairing.message)

        interfaces = self.runtime.ipheth_interfaces()
        if len(interfaces) > 1:
            self._forget_lease()
            return self._fail(
                "multiple_devices",
                "Multiple iPhone USB network interfaces are present",
                safe=False,
            )
        if not interfaces:
            self._forget_lease()
            message = "iPhone is paired but no ipheth network interface is available"
            if not self.runtime.ipheth_driver_active():
                message = "iPhone is paired but the host ipheth driver is not active"
            return self._fail("waiting_for_interface", message)

        self.interface = interfaces[0]
        return self._resolve_network(
            self.interface,
            self.runtime.interface_carrier(self.interface),
            management,
            carrier_state="waiting_for_hotspot",
            carrier_message=(
                "Enable Personal Hotspot and Allow Others to Join on the iPhone"
            ),
        )

    def cleanup(self) -> None:
        self.runtime.stop_usbmuxd()
        super().cleanup()

    def _reset_status(self) -> None:
        super()._reset_status()
        self.device_udid = None
