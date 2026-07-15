from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from .command import RunCommand
from .config import RUN_DIR, GatewayConfig
from .errors import GatewayError
from .upstream_iphone_resolver import (
    LeaseResolution,
    host_conflict_message,
    host_managed_conflict,
    resolved_interface,
)
from .upstream_iphone_cleanup import discard_owned_lease
from .upstream_iphone_runtime import IPhoneUsbRuntime
from .upstream_models import ResolvedUpstream


class IPhoneUsbUpstream:
    HOST_CONFLICT_MESSAGE = host_conflict_message()

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
        udhcpc_script: Path = Path("/app/udhcpc.script"),
        popen: Callable[..., subprocess.Popen[str]] | None = None,
        which: Callable[[str], str | None] | None = None,
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
            udhcpc_script=udhcpc_script,
            popen=popen,
            which=which,
        )
        self.pairing_state = "not_applicable"
        self.pairing_message: str | None = None
        self.device_udid: str | None = None
        self.interface: str | None = None
        self.lease_owner: str | None = None
        self.fallback_safe = True

    def runtime_status(self) -> dict[str, object]:
        return {
            "upstream_pairing_state": self.pairing_state,
            "upstream_pairing_message": self.pairing_message,
            "upstream_device_udid": self.device_udid,
            "upstream_runtime_interface": self.interface,
            "upstream_lockdown_path": str(self.runtime.lockdown_dir),
            "upstream_lease_owner": self.lease_owner,
        }

    def resolve(self) -> tuple[ResolvedUpstream | None, list[str]]:
        self.pairing_state = "not_ready"
        self.pairing_message = None
        self.device_udid = None
        self.interface = None
        self.lease_owner = None
        self.fallback_safe = True

        errors = self.runtime.capability_errors()
        if errors:
            self._discard_owned_lease()
            return None, errors

        apple_present = self.runtime.apple_usb_present()
        interface = self.runtime.ipheth_interface()
        self.interface = interface
        if self._set_ownership_conflict(interface):
            return None, [self.HOST_CONFLICT_MESSAGE]

        try:
            self.runtime.ensure_usbmuxd()
        except GatewayError as err:
            self.pairing_state = "daemon_failed"
            self.pairing_message = str(err)
            return None, [self.pairing_message]

        udids = self.runtime.connected_udids()
        if not udids:
            self._discard_owned_lease()
            if apple_present and not self._ipheth_driver_active():
                message = "Apple USB device is present but the host ipheth driver is not active"
            else:
                message = "Connect a single trusted iPhone with Personal Hotspot enabled"
            self.pairing_state = "waiting_for_device"
            self.pairing_message = message
            return None, [message]
        if len(udids) > 1:
            self._discard_owned_lease()
            self.pairing_state = "multiple_devices"
            self.pairing_message = "Connect only one iPhone USB upstream at a time"
            return None, [self.pairing_message]

        udid = udids[0]
        self.device_udid = udid
        if not self.runtime.validate_pairing(udid):
            pairing = self.runtime.pair_device(udid)
            self.pairing_state = pairing.state
            self.pairing_message = pairing.message
            if not pairing.paired:
                self._discard_owned_lease()
                assert pairing.message is not None
                return None, [pairing.message]

        interface = self.runtime.ipheth_interface()
        self.interface = interface
        if interface is None:
            self._discard_owned_lease()
            message = "iPhone is paired but no ipheth network interface is available"
            if not self._ipheth_driver_active():
                message = "iPhone is paired but the host ipheth driver is not active"
            self.pairing_state = "waiting_for_interface"
            self.pairing_message = message
            return None, [message]

        self.runtime.ensure_dhcp(interface)
        lease = self._resolved_interface(interface)
        if lease.error:
            message = lease.error
            if lease.owner == "app":
                try:
                    self._discard_owned_lease()
                except (GatewayError, OSError, subprocess.SubprocessError) as err:
                    self.fallback_safe = False
                    message = f"{message}; cleanup failed: {err}"
            else:
                self.fallback_safe = False
            self.pairing_state = (
                "waiting_for_dhcp"
                if lease.error == "iPhone USB lease is stale"
                and self.fallback_safe
                else "invalid_lease"
            )
            self.pairing_message = message
            return None, [message]
        if lease.owner == "external":
            self._mark_ownership_conflict()
            return None, [self.HOST_CONFLICT_MESSAGE]
        if lease.upstream is None:
            self.pairing_state = "waiting_for_dhcp"
            self.pairing_message = (
                "Waiting for the iPhone USB tether interface to acquire DHCP"
            )
            return None, [self.pairing_message]
        self.pairing_state = "paired"
        self.pairing_message = None
        return lease.upstream, []

    def fallback_allowed(self) -> bool:
        if self._set_ownership_conflict(
            self.runtime.ipheth_interface()
        ):
            return False
        return self.fallback_safe

    def cleanup(self) -> None:
        self._discard_owned_lease()
        self.runtime.stop_usbmuxd()

    def _discard_owned_lease(self) -> None:
        discard_owned_lease(
            self.runtime,
            self.run,
        )
        self.lease_owner = None

    def _set_ownership_conflict(self, interface: str | None) -> bool:
        if not interface or not host_managed_conflict(
            self.run,
            self.runtime.lease_path,
            interface,
        ):
            return False
        self._mark_ownership_conflict()
        return True

    def _mark_ownership_conflict(self) -> None:
        self.runtime.stop_dhcp()
        self.fallback_safe = False
        self.pairing_state = "ownership_conflict"
        self.pairing_message = self.HOST_CONFLICT_MESSAGE

    def _resolved_interface(
        self,
        interface: str,
    ) -> LeaseResolution:
        lease = resolved_interface(
            self.config,
            self.run,
            self.runtime.lease_path,
            interface,
        )
        self.lease_owner = lease.owner
        return lease

    def _ipheth_driver_active(self) -> bool:
        return self.runtime.ipheth_driver_active()
