from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .command import RunCommand, run_json
from .errors import GatewayError

if TYPE_CHECKING:
    from .config import GatewayConfig


@dataclass(frozen=True)
class ManagementBaseline:
    interface: str
    address: str


def _interface_addresses(
    run: RunCommand,
    interface: str,
    *,
    family: int = 4,
) -> set[str]:
    data = run_json(
        run,
        "ip",
        f"-{family}",
        "-j",
        "address",
        "show",
        "dev",
        interface,
    )
    addresses: set[str] = set()
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        entries = item.get("addr_info", [])
        for address in entries if isinstance(entries, list) else []:
            if not isinstance(address, dict):
                continue
            expected_family = "inet" if family == 4 else "inet6"
            if address.get("family") != expected_family:
                continue
            local = address.get("local")
            prefix = address.get("prefixlen")
            if isinstance(local, str) and isinstance(prefix, int):
                addresses.add(f"{local}/{prefix}")
    return addresses


def detect_management(run: RunCommand) -> ManagementBaseline:
    routes = run_json(
        run,
        "ip",
        "-4",
        "-j",
        "route",
        "show",
        "table",
        "main",
        "default",
    )
    defaults = [
        route
        for route in (routes if isinstance(routes, list) else [])
        if isinstance(route, dict) and isinstance(route.get("dev"), str)
    ]
    interfaces = {str(route["dev"]) for route in defaults}
    if len(interfaces) != 1:
        raise GatewayError("Host must have exactly one management default route")
    interface = interfaces.pop()
    addresses = _interface_addresses(run, interface)
    preferred = {
        str(source)
        for route in defaults
        for source in (route.get("prefsrc"), route.get("src"))
        if isinstance(source, str)
    }
    matching = [
        address
        for address in addresses
        if address.partition("/")[0] in preferred
    ]
    if len(matching) == 1:
        return ManagementBaseline(interface, matching[0])
    if len(addresses) != 1:
        raise GatewayError(
            "Management interface must have one unambiguous IPv4 address"
        )
    return ManagementBaseline(interface, next(iter(addresses)))


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
        return _interface_addresses(self.run, interface, family=family)

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
