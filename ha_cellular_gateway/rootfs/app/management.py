from __future__ import annotations

import subprocess
from dataclasses import dataclass

from .command import RunCommand, run_json
from .errors import GatewayError


@dataclass(frozen=True)
class ManagementBaseline:
    interface: str
    address: str


def interface_addresses(
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
    addresses = interface_addresses(run, interface)
    preferred = {
        str(source)
        for route in defaults
        for source in (route.get("prefsrc"), route.get("src"))
        if isinstance(source, str)
    }
    matching = [
        address for address in addresses if address.partition("/")[0] in preferred
    ]
    if len(matching) == 1:
        return ManagementBaseline(interface, matching[0])
    if len(addresses) != 1:
        raise GatewayError(
            "Management interface must have one unambiguous IPv4 address"
        )
    return ManagementBaseline(interface, next(iter(addresses)))


def resolve_management(run: RunCommand) -> ManagementBaseline | None:
    try:
        return detect_management(run)
    except GatewayError, OSError, subprocess.SubprocessError, ValueError:
        return None
