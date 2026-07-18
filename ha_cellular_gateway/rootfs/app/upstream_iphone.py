from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from .command import RunCommand
from .config import RUN_DIR, GatewayConfig
from .errors import GatewayError
from .networkmanager import (
    ACTIVATION_COOLDOWN_SECONDS,
    LEASE_OWNER,
    NetworkManagerIphone,
    NetworkManagerResult,
)
from .networkmanager_profile import DHCP_TIMEOUT_SECONDS
from .upstream_iphone_runtime import IPhoneUsbRuntime
from .upstream_models import ResolvedUpstream

if TYPE_CHECKING:
    from .management import ManagementBaseline

UpstreamResolution = tuple[ResolvedUpstream | None, list[str]]


class IPhoneUsbUpstream:
    LEASE_GRACE_SECONDS = max(
        ACTIVATION_COOLDOWN_SECONDS,
        DHCP_TIMEOUT_SECONDS,
    ) + 5

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
        self.run = run
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
        self.nm = network_manager or NetworkManagerIphone(
            config,
            run,
            monotonic=monotonic,
        )
        self._monotonic = monotonic
        self.pairing_state = "not_applicable"
        self.pairing_message: str | None = None
        self.device_udid: str | None = None
        self.interface: str | None = None
        self.lease_owner: str | None = None
        self.fallback_safe = True
        self._last_lease: tuple[ResolvedUpstream, float] | None = None

    def runtime_status(self) -> dict[str, object]:
        return {
            "upstream_pairing_state": self.pairing_state,
            "upstream_pairing_message": self.pairing_message,
            "upstream_device_udid": self.device_udid,
            "upstream_runtime_interface": self.interface,
            "upstream_lockdown_path": str(self.runtime.lockdown_dir),
            "upstream_lease_owner": self.lease_owner,
        }

    def resolve(
        self,
        management: ManagementBaseline | None = None,
    ) -> UpstreamResolution:
        self._reset_status()
        self.pairing_state = "not_ready"

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
        if self.runtime.interface_carrier(self.interface) is False:
            self._forget_lease()
            return self._fail(
                "waiting_for_hotspot",
                "Enable Personal Hotspot and Allow Others to Join on the iPhone",
            )
        return self._consume(self.nm.inspect(self.interface, management))

    def fallback_allowed(self) -> bool:
        return self.fallback_safe

    def cleanup(self) -> None:
        self._forget_lease()
        self.runtime.stop_usbmuxd()
        self._reset_status()

    def _consume(self, result: NetworkManagerResult) -> UpstreamResolution:
        if result.state == "active":
            assert result.upstream is not None
            self._last_lease = (result.upstream, self._monotonic())
            self.lease_owner = LEASE_OWNER
            self.pairing_state = "paired"
            self.pairing_message = None
            return result.upstream, []
        if result.state == "waiting":
            grace = self._grace_lease()
            if grace is not None:
                self.lease_owner = LEASE_OWNER
                self.pairing_state = "paired"
                self.pairing_message = None
                return grace, []
            assert result.error is not None
            return self._fail("waiting_for_profile", result.error)
        self._forget_lease()
        state = "profile_conflict" if result.state == "foreign" else "invalid_lease"
        assert result.error is not None
        return self._fail(state, result.error, safe=False)

    def _fail(
        self,
        state: str,
        message: str,
        *,
        safe: bool = True,
    ) -> UpstreamResolution:
        self.pairing_state = state
        self.pairing_message = message
        if not safe:
            self.fallback_safe = False
        return None, [message]

    def _grace_lease(self) -> ResolvedUpstream | None:
        if self._last_lease is None:
            return None
        upstream, seen = self._last_lease
        if self._monotonic() - seen < self.LEASE_GRACE_SECONDS:
            return upstream
        self._last_lease = None
        return None

    def _forget_lease(self) -> None:
        self._last_lease = None

    def _reset_status(self) -> None:
        self.pairing_state = "not_applicable"
        self.pairing_message = None
        self.device_udid = None
        self.interface = None
        self.lease_owner = None
        self.fallback_safe = True
