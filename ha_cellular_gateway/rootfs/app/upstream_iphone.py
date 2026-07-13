from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from .config import RUN_DIR, GatewayConfig
from .errors import GatewayError
from .upstream_lease import (
    inspect_external_lease,
    load_app_lease,
    validate_dynamic_lease,
)
from .upstream_models import ResolvedUpstream


RunCommand = Callable[..., subprocess.CompletedProcess[str]]


class IPhoneUsbUpstream:
    APPLE_VENDOR = "05ac"
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
        self.run_dir = run_dir
        self.lockdown_dir = lockdown_dir
        self.usb_root = usb_root
        self.sys_net_root = sys_net_root
        self.sys_usb_root = sys_usb_root
        self.udhcpc_script = udhcpc_script
        self.popen = popen or subprocess.Popen
        self.which = which or shutil.which
        self.usbmuxd_pid = self.run_dir / "usbmuxd.pid"
        self.lease_path = self.run_dir / "iphone-usb-lease.json"
        self.usbmuxd_process: subprocess.Popen[str] | None = None
        self.udhcpc_process: subprocess.Popen[str] | None = None
        self.udhcpc_interface: str | None = None
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
            "upstream_lockdown_path": str(self.lockdown_dir),
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

        errors = self._capability_errors()
        if errors:
            return None, errors

        apple_present = self._apple_usb_present()
        interface = self._ipheth_interface()
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
            self._ensure_usbmuxd()
        except GatewayError as err:
            self.pairing_state = "daemon_failed"
            self.pairing_message = str(err)
            return None, [self.pairing_message]

        udids = self._connected_udids()
        if not udids:
            self._stop_dhcp()
            if apple_present and not self._ipheth_driver_active():
                message = "Apple USB device is present but the host ipheth driver is not active"
            else:
                message = "Connect a single trusted iPhone with Personal Hotspot enabled"
            self.pairing_state = "waiting_for_device"
            self.pairing_message = message
            return None, [message]
        if len(udids) > 1:
            self._stop_dhcp()
            self.pairing_state = "multiple_devices"
            self.pairing_message = "Connect only one iPhone USB upstream at a time"
            return None, [self.pairing_message]

        udid = udids[0]
        self.device_udid = udid
        if not self._validate_pairing(udid) and not self._pair_device(udid):
            self._stop_dhcp()
            assert self.pairing_message is not None
            return None, [self.pairing_message]

        interface = self._ipheth_interface()
        self.interface = interface
        if interface is None:
            self._stop_dhcp()
            message = "iPhone is paired but no ipheth network interface is available"
            if not self._ipheth_driver_active():
                message = "iPhone is paired but the host ipheth driver is not active"
            self.pairing_state = "waiting_for_interface"
            self.pairing_message = message
            return None, [message]

        if self._host_managed_conflict(interface):
            self._stop_dhcp()
            self.pairing_state = "ownership_conflict"
            self.pairing_message = self.HOST_CONFLICT_MESSAGE
            return None, [self.pairing_message]

        self._ensure_dhcp(interface)
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
        self._stop_dhcp()
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
        self._stop_usbmuxd()

    def _capability_errors(self) -> list[str]:
        errors: list[str] = []
        for command in ("usbmuxd", "idevice_id", "idevicepair", "udhcpc"):
            if self.which(command) is None:
                errors.append(f"Required command is unavailable: {command}")
        if not self.udhcpc_script.exists():
            errors.append("Required udhcpc helper script is unavailable")
        if not self.usb_root.exists():
            errors.append("USB device access is unavailable; enable the app usb permission")
        return errors

    def _ensure_usbmuxd(self) -> None:
        if self.usbmuxd_process and self.usbmuxd_process.poll() is None:
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.lockdown_dir.mkdir(parents=True, exist_ok=True)
        self.usbmuxd_process = self.popen(
            [
                "usbmuxd",
                "--foreground",
                "--pidfile",
                str(self.usbmuxd_pid),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if self.usbmuxd_process.poll() is None:
            return
        stdout, stderr = self.usbmuxd_process.communicate(timeout=1)
        self.usbmuxd_process = None
        detail = "; ".join(
            part.strip()
            for part in (stdout, stderr)
            if part and part.strip()
        ) or "process exited immediately"
        raise GatewayError(f"usbmuxd failed to start: {detail}")

    def _stop_usbmuxd(self) -> None:
        self._stop_process(self.usbmuxd_process)
        self.usbmuxd_process = None

    def _ensure_dhcp(self, interface: str) -> None:
        if (
            self.udhcpc_process
            and self.udhcpc_process.poll() is None
            and self.udhcpc_interface == interface
        ):
            return
        self._stop_dhcp()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.udhcpc_process = self.popen(
            [
                "udhcpc",
                "--foreground",
                "--interface",
                interface,
                "--script",
                str(self.udhcpc_script),
            ],
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.udhcpc_interface = interface

    def _stop_dhcp(self) -> None:
        self._stop_process(self.udhcpc_process)
        self.udhcpc_process = None
        self.udhcpc_interface = None

    @staticmethod
    def _stop_process(process: subprocess.Popen[str] | None) -> None:
        if not process or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def _connected_udids(self) -> list[str]:
        result = self.run("idevice_id", "--list", check=False)
        output = (result.stdout or "").strip()
        if result.returncode != 0 or not output:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()]

    def _validate_pairing(self, udid: str) -> bool:
        result = self.run("idevicepair", "--udid", udid, "validate", check=False)
        return result.returncode == 0

    def _pair_device(self, udid: str) -> bool:
        result = self.run("idevicepair", "--udid", udid, "pair", check=False, timeout=30)
        if result.returncode == 0:
            self.pairing_state = "paired"
            return True
        text = "\n".join(part for part in (result.stdout, result.stderr) if part).lower()
        if "trust dialog" in text or "user denied" in text:
            self.pairing_state = "waiting_for_trust"
            self.pairing_message = (
                "Unlock the iPhone, tap Trust, keep Personal Hotspot enabled, "
                "then press Reapply gateway state"
            )
        elif "passcode" in text:
            self.pairing_state = "waiting_for_unlock"
            self.pairing_message = (
                "Unlock the iPhone, leave it on the Home screen, then retry pairing"
            )
        else:
            self.pairing_state = "pairing_failed"
            self.pairing_message = (
                "iPhone USB pairing failed; reconnect the cable, confirm Trust on the phone, "
                "then press Reapply gateway state"
            )
        return False

    def _resolved_interface(
        self,
        interface: str,
    ) -> tuple[ResolvedUpstream | None, str | None]:
        app_lease = load_app_lease(self.lease_path, interface)
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
        if load_app_lease(self.lease_path, interface) is not None:
            return False
        state = self._external_lease(interface)
        return state.address is not None or state.has_default_route

    def _external_lease(self, interface: str):
        return inspect_external_lease(
            self._read_json(
                "ip",
                "-4",
                "-j",
                "address",
                "show",
                "dev",
                interface,
            ),
            self._read_json(
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
        if self.udhcpc_interface and load_app_lease(self.lease_path, self.udhcpc_interface):
            return self.udhcpc_interface
        if self.interface and load_app_lease(self.lease_path, self.interface):
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

    def _apple_usb_present(self) -> bool:
        if not self.sys_usb_root.exists():
            return False
        for device in self.sys_usb_root.iterdir():
            try:
                if (device / "idVendor").read_text(encoding="utf-8").strip().lower() == self.APPLE_VENDOR:
                    return True
            except OSError:
                continue
        return False

    def _ipheth_driver_active(self) -> bool:
        return Path("/sys/module/ipheth").exists() or Path("/sys/bus/usb/drivers/ipheth").exists()

    def _ipheth_interface(self) -> str | None:
        if not self.sys_net_root.exists():
            return None
        matches: list[str] = []
        for interface in self.sys_net_root.iterdir():
            try:
                driver = (interface / "device" / "driver").resolve().name
            except OSError:
                continue
            if driver == "ipheth":
                matches.append(interface.name)
        if len(matches) == 1:
            return matches[0]
        return None

    def _read_json(self, *args: str) -> object:
        result = self.run(*args)
        return json.loads(result.stdout or "[]")
