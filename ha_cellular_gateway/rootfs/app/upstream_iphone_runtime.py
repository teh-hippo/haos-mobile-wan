from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .command import RunCommand, stop_process
from .errors import GatewayError


@dataclass(frozen=True)
class PairingResult:
    paired: bool
    state: str
    message: str | None = None


class IPhoneUsbRuntime:
    APPLE_VENDOR = "05ac"

    def __init__(
        self,
        run: RunCommand,
        *,
        run_dir: Path,
        lockdown_dir: Path,
        usb_root: Path,
        sys_net_root: Path,
        sys_usb_root: Path,
        udhcpc_script: Path,
        popen: Callable[..., subprocess.Popen[str]] | None = None,
        which: Callable[[str], str | None] | None = None,
    ) -> None:
        self.run = run
        self.run_dir = run_dir
        self.lockdown_dir = lockdown_dir
        self.usb_root = usb_root
        self.sys_net_root = sys_net_root
        self.sys_usb_root = sys_usb_root
        self.udhcpc_script = udhcpc_script
        self.popen = popen or subprocess.Popen
        self.which = which or shutil.which
        self.usbmuxd_pid = run_dir / "usbmuxd.pid"
        self.usbmuxd_log = run_dir / "usbmuxd.log"
        self.lease_path = run_dir / "iphone-usb-lease.json"
        self.usbmuxd_process: subprocess.Popen[str] | None = None
        self.udhcpc_process: subprocess.Popen[str] | None = None
        self.udhcpc_interface: str | None = None

    def capability_errors(self) -> list[str]:
        errors: list[str] = []
        for command in ("usbmuxd", "idevice_id", "idevicepair", "udhcpc"):
            if self.which(command) is None:
                errors.append(f"Required command is unavailable: {command}")
        if not self.udhcpc_script.exists():
            errors.append("Required udhcpc helper script is unavailable")
        if not self.usb_root.exists():
            errors.append(
                "USB device access is unavailable; enable the app usb permission"
            )
        return errors

    def ensure_usbmuxd(self) -> None:
        if self.usbmuxd_process and self.usbmuxd_process.poll() is None:
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.lockdown_dir.mkdir(parents=True, exist_ok=True)
        self.usbmuxd_log.write_text("", encoding="utf-8")
        with self.usbmuxd_log.open("a", encoding="utf-8") as log_file:
            self.usbmuxd_process = self.popen(
                [
                    "usbmuxd",
                    "--foreground",
                    "--pidfile",
                    str(self.usbmuxd_pid),
                ],
                text=True,
                stdout=log_file,
                stderr=log_file,
            )
        try:
            self.usbmuxd_process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            return
        self.usbmuxd_process = None
        detail = self.usbmuxd_log.read_text(encoding="utf-8").strip()
        if detail:
            detail = "; ".join(
                line.strip() for line in detail.splitlines() if line.strip()
            )
        else:
            detail = "process exited immediately"
        raise GatewayError(f"usbmuxd failed to start: {detail}")

    def stop_usbmuxd(self) -> None:
        stop_process(self.usbmuxd_process)
        self.usbmuxd_process = None

    def ensure_dhcp(self, interface: str) -> None:
        if (
            self.udhcpc_process
            and self.udhcpc_process.poll() is None
            and self.udhcpc_interface == interface
        ):
            return
        self.stop_dhcp()
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

    def stop_dhcp(self) -> None:
        stop_process(self.udhcpc_process)
        self.udhcpc_process = None
        self.udhcpc_interface = None

    def connected_udids(self) -> list[str]:
        result = self.run("idevice_id", "--list", check=False)
        output = (result.stdout or "").strip()
        if result.returncode != 0 or not output:
            return []
        return [line.strip() for line in output.splitlines() if line.strip()]

    def validate_pairing(self, udid: str) -> bool:
        result = self.run("idevicepair", "--udid", udid, "validate", check=False)
        return result.returncode == 0

    def pair_device(self, udid: str) -> PairingResult:
        result = self.run(
            "idevicepair",
            "--udid",
            udid,
            "pair",
            check=False,
            timeout=30,
        )
        if result.returncode == 0:
            return PairingResult(True, "paired")
        text = "\n".join(
            part for part in (result.stdout, result.stderr) if part
        ).lower()
        if "trust dialog" in text or "user denied" in text:
            return PairingResult(
                False,
                "waiting_for_trust",
                "Unlock the iPhone, tap Trust, keep Personal Hotspot enabled, "
                "then press Reapply gateway state",
            )
        if "passcode" in text:
            return PairingResult(
                False,
                "waiting_for_unlock",
                "Unlock the iPhone, leave it on the Home screen, then retry pairing",
            )
        return PairingResult(
            False,
            "pairing_failed",
            "iPhone USB pairing failed; reconnect the cable, confirm Trust on the "
            "phone, then press Reapply gateway state",
        )

    def apple_usb_present(self) -> bool:
        if not self.sys_usb_root.exists():
            return False
        for device in self.sys_usb_root.iterdir():
            try:
                vendor = (device / "idVendor").read_text(encoding="utf-8")
            except OSError:
                continue
            if vendor.strip().lower() == self.APPLE_VENDOR:
                return True
        return False

    @staticmethod
    def ipheth_driver_active() -> bool:
        return Path("/sys/module/ipheth").exists() or Path(
            "/sys/bus/usb/drivers/ipheth"
        ).exists()

    def ipheth_interface(self) -> str | None:
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
        return matches[0] if len(matches) == 1 else None
