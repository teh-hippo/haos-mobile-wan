from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from .command import RunCommand
from .errors import GatewayError
from .management import interface_addresses

if TYPE_CHECKING:
    from .config import GatewayConfig


class DownstreamInterface:
    def __init__(
        self,
        config: GatewayConfig,
        run: RunCommand,
        read_text: Callable[[Path], str],
        *,
        sys_net_root: Path = Path("/sys/class/net"),
    ) -> None:
        self.config = config
        self.run = run
        self.read_text = read_text
        self.sys_net_root = sys_net_root

    def addresses(self, interface: str, *, family: int = 4) -> set[str]:
        return interface_addresses(self.run, interface, family=family)

    def mac(self, interface: str) -> str | None:
        try:
            return self.read_text(
                self.sys_net_root / interface / "address"
            ).strip().lower()
        except (KeyError, OSError):
            return None

    def candidates(self) -> list[str]:
        try:
            interfaces = tuple(self.sys_net_root.iterdir())
        except OSError:
            return []
        return sorted(
            interface.name
            for interface in interfaces
            if self._is_usb_ethernet(interface)
            and interface.name
            not in {
                self.config.management_interface,
                self.config.upstream_interface,
            }
        )

    def find(self) -> str | None:
        if self.config.downstream_mac:
            for interface in self.candidates():
                if self.mac(interface) == self.config.downstream_mac:
                    return interface
            return None
        candidates = self.candidates()
        return candidates[0] if len(candidates) == 1 else None

    def selection_error(self) -> str:
        if self.config.downstream_mac:
            return "Configured downstream NIC is not present"
        candidates = self.candidates()
        if not candidates:
            return "USB Ethernet downstream is not present"
        return "Multiple USB Ethernet adapters detected; set downstream_mac"

    def address_errors(
        self,
        interface: str,
        *,
        owned: bool,
    ) -> list[str]:
        addresses = self.addresses(interface)
        desired = self.config.downstream_address
        if owned:
            if desired not in addresses:
                return ["App-owned downstream address is unavailable"]
            if addresses != {desired}:
                return ["Downstream interface has unexpected IPv4 addresses"]
            return []
        if addresses:
            return ["Downstream interface has host-managed IPv4 addresses"]
        return []

    def apply(self, interface: str) -> None:
        if self.addresses(interface):
            raise GatewayError(
                "Downstream interface has host-managed IPv4 addresses"
            )
        self.run(
            "ip",
            "-4",
            "address",
            "add",
            self.config.downstream_address,
            "dev",
            interface,
        )
        if self.config.downstream_address not in self.addresses(interface):
            raise GatewayError("App-owned downstream address is unavailable")

    def cleanup(self, ownership: dict[str, object] | None) -> None:
        if not self.owns_address(ownership):
            return
        assert ownership is not None
        interface = str(ownership["downstream"])
        address = str(ownership["downstream_address"])
        self.run(
            "ip",
            "-4",
            "address",
            "del",
            address,
            "dev",
            interface,
            check=False,
        )
        if not (self.sys_net_root / interface).exists():
            return
        if address in self.addresses(interface):
            raise GatewayError("Could not remove the app-owned downstream address")

    @staticmethod
    def owns_address(
        ownership: dict[str, object] | None,
        interface: str | None = None,
    ) -> bool:
        return bool(
            ownership
            and ownership.get("downstream_address_owned") is True
            and (
                interface is None
                or ownership.get("downstream") == interface
            )
        )

    @staticmethod
    def _is_usb_ethernet(interface: Path) -> bool:
        if (interface / "wireless").exists():
            return False
        device = interface / "device"
        try:
            driver = (device / "driver").resolve(strict=True).name
            device_path = device.resolve(strict=True)
        except OSError:
            return False
        return driver != "ipheth" and any(
            re.fullmatch(r"usb\d+", part) for part in device_path.parts
        )
