from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from .command import RunCommand, run_json
from .config import RUN_DIR, GatewayConfig
from .errors import GatewayError
from .upstream_lease import (
    DynamicLease,
    inspect_external_lease,
    load_app_lease,
    validate_dynamic_lease,
)
from .upstream_iphone_runtime import IPhoneUsbRuntime
from .upstream_models import ResolvedUpstream


class IPhoneUsbUpstream:
    HOST_CONFLICT_MESSAGE = (
        "iPhone USB interface is already host-managed; leave ipheth unmanaged "
        "so the app can own DHCP and the main default route"
    )

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
        *,
        allow_mutation: bool,
    ) -> tuple[ResolvedUpstream | None, list[str]]:
        self.pairing_state = "not_ready"
        self.pairing_message = None
        self.device_udid = None
        self.interface = None
        self.lease_owner = None

        errors = self.runtime.capability_errors()
        if errors:
            return None, errors

        apple_present = self.runtime.apple_usb_present()
        interface = self.runtime.ipheth_interface()
        self.interface = interface

        if not allow_mutation:
            if interface is None:
                message = (
                    "iPhone USB commissioning requires dry_run false so the app can "
                    "pair and acquire DHCP without enabling the downstream gateway"
                )
                if apple_present and not self._ipheth_driver_active():
                    message = "Apple USB device is present but the host ipheth driver is not active"
                self.pairing_state = "dry_run_blocked"
                self.pairing_message = message
                return None, [message]
            resolved, error = self._resolved_interface(interface)
            if error:
                self.pairing_state = "invalid_lease"
                self.pairing_message = error
                return None, [error]
            if resolved is None:
                message = "iPhone USB upstream is present but has no DHCP lease"
                self.pairing_state = "waiting_for_dhcp"
                self.pairing_message = message
                return None, [message]
            self.pairing_state = "paired"
            return resolved, []

        try:
            self.runtime.ensure_usbmuxd()
        except GatewayError as err:
            self.pairing_state = "daemon_failed"
            self.pairing_message = str(err)
            return None, [self.pairing_message]

        udids = self.runtime.connected_udids()
        if not udids:
            self.runtime.stop_dhcp()
            if apple_present and not self._ipheth_driver_active():
                message = "Apple USB device is present but the host ipheth driver is not active"
            else:
                message = "Connect a single trusted iPhone with Personal Hotspot enabled"
            self.pairing_state = "waiting_for_device"
            self.pairing_message = message
            return None, [message]
        if len(udids) > 1:
            self.runtime.stop_dhcp()
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
                self.runtime.stop_dhcp()
                assert pairing.message is not None
                return None, [pairing.message]

        interface = self.runtime.ipheth_interface()
        self.interface = interface
        if interface is None:
            self.runtime.stop_dhcp()
            message = "iPhone is paired but no ipheth network interface is available"
            if not self._ipheth_driver_active():
                message = "iPhone is paired but the host ipheth driver is not active"
            self.pairing_state = "waiting_for_interface"
            self.pairing_message = message
            return None, [message]

        if self._host_managed_conflict(interface):
            self.runtime.stop_dhcp()
            self.pairing_state = "ownership_conflict"
            self.pairing_message = self.HOST_CONFLICT_MESSAGE
            return None, [self.pairing_message]

        self.runtime.ensure_dhcp(interface)
        resolved, error = self._resolved_interface(interface)
        if error:
            self.pairing_state = "invalid_lease"
            self.pairing_message = error
            return None, [error]
        if resolved is None:
            self.pairing_state = "waiting_for_dhcp"
            self.pairing_message = (
                "Waiting for the iPhone USB tether interface to acquire DHCP"
            )
            return None, [self.pairing_message]
        self.pairing_state = "paired"
        self.pairing_message = None
        return resolved, []

    def cleanup(self) -> None:
        interface = self._owned_interface()
        self.runtime.stop_dhcp()
        if interface:
            self.run(
                "ip",
                "-4",
                "address",
                "flush",
                "dev",
                interface,
                "scope",
                "global",
                check=False,
            )
            self._remove_main_defaults(interface)
        self.lease_owner = None
        self.runtime.stop_usbmuxd()

    def _resolved_interface(
        self,
        interface: str,
    ) -> tuple[ResolvedUpstream | None, str | None]:
        app_lease = load_app_lease(self.runtime.lease_path, interface)
        if app_lease is not None:
            self.lease_owner = "app"
            return validate_dynamic_lease(self.config, interface, *app_lease)
        state = self._external_lease(interface)
        if state.address is None and not state.has_default_route:
            return None, None
        self.lease_owner = "external"
        if state.address is None or state.gateway is None:
            return None, self.HOST_CONFLICT_MESSAGE
        return validate_dynamic_lease(
            self.config,
            interface,
            state.address,
            state.gateway,
        )

    def _host_managed_conflict(self, interface: str) -> bool:
        if load_app_lease(self.runtime.lease_path, interface) is not None:
            return False
        state = self._external_lease(interface)
        return state.address is not None or state.has_default_route

    def _external_lease(self, interface: str) -> DynamicLease:
        return inspect_external_lease(
            run_json(
                self.run,
                "ip",
                "-4",
                "-j",
                "address",
                "show",
                "dev",
                interface,
            ),
            run_json(
                self.run,
                "ip",
                "-4",
                "-j",
                "route",
                "show",
                "table",
                "main",
                "default",
            ),
            interface,
        )

    def _owned_interface(self) -> str | None:
        interface = self.runtime.udhcpc_interface
        if interface and load_app_lease(self.runtime.lease_path, interface):
            return interface
        if self.interface and load_app_lease(self.runtime.lease_path, self.interface):
            return self.interface
        return None

    def _remove_main_defaults(self, interface: str) -> None:
        while (
            self.run(
                "ip",
                "route",
                "del",
                "default",
                "dev",
                interface,
                check=False,
            ).returncode
            == 0
        ):
            pass

    def _ipheth_driver_active(self) -> bool:
        return self.runtime.ipheth_driver_active()
