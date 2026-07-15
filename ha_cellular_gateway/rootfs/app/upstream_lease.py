from __future__ import annotations

import fcntl
import ipaddress
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .config import GatewayConfig
from .const import IPHONE_USB
from .upstream_models import ResolvedUpstream


@dataclass(frozen=True)
class DynamicLease:
    interface: str
    addresses: tuple[str, ...]
    gateway: str | None
    has_default_route: bool

    @property
    def address(self) -> str | None:
        return self.addresses[0] if len(self.addresses) == 1 else None


@contextmanager
def lease_lock(
    path: Path,
    *,
    exclusive: bool = False,
) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as lock:
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(lock, operation)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def load_app_lease_record(
    path: Path,
) -> tuple[str, str, str] | None:
    if not path.exists():
        return None
    try:
        lease = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(lease, dict)
        or not isinstance(lease.get("interface"), str)
        or "address" not in lease
        or "gateway" not in lease
    ):
        return None
    owner = str(lease.get("owner", "app"))
    if owner != "app":
        return None
    return (
        str(lease["interface"]),
        str(lease["address"]),
        str(lease["gateway"]),
    )


def load_app_lease(path: Path, interface: str) -> tuple[str, str] | None:
    record = load_app_lease_record(path)
    if record is None or record[0] != interface:
        return None
    return record[1], record[2]


def write_app_lease_record(
    path: Path,
    interface: str,
    address: str,
    gateway: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(
                {
                    "owner": "app",
                    "interface": interface,
                    "address": address,
                    "gateway": gateway,
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def inspect_external_lease(
    address_data: object,
    routes: object,
    interface: str,
) -> DynamicLease:
    live_addresses: list[str] = []
    gateway: str | None = None
    has_default_route = False
    for item in address_data if isinstance(address_data, list) else []:
        for entry in item.get("addr_info", []):
            if entry.get("family") == "inet":
                live_addresses.append(
                    f"{entry['local']}/{entry['prefixlen']}"
                )
    for route in routes if isinstance(routes, list) else []:
        if route.get("dev") != interface or route.get("dst") != "default":
            continue
        has_default_route = True
        if route.get("gateway"):
            gateway = str(route["gateway"])
            break
    return DynamicLease(
        interface=interface,
        addresses=tuple(live_addresses),
        gateway=gateway,
        has_default_route=has_default_route,
    )


def validate_dynamic_lease(
    config: GatewayConfig,
    interface: str,
    address: str,
    gateway: str,
) -> tuple[ResolvedUpstream | None, str | None]:
    try:
        upstream = ipaddress.ip_interface(address)
        peer = ipaddress.ip_address(gateway)
        management = ipaddress.ip_interface(config.management_address)
        downstream = ipaddress.ip_interface(config.downstream_address)
    except ValueError as err:
        return None, f"iPhone USB lease is invalid: {err}"
    if upstream.version != 4 or peer.version != 4:
        return None, "iPhone USB lease must use IPv4"
    if upstream.ip in {
        upstream.network.network_address,
        upstream.network.broadcast_address,
    }:
        return None, "iPhone USB lease address is not a usable host address"
    if peer not in upstream.network:
        return None, "iPhone USB lease gateway is outside the lease subnet"
    if peer in {
        upstream.ip,
        upstream.network.network_address,
        upstream.network.broadcast_address,
    }:
        return None, "iPhone USB lease gateway is not a usable peer address"
    if upstream.network.overlaps(management.network):
        return None, "iPhone USB lease overlaps the management network"
    if upstream.network.overlaps(downstream.network):
        return None, "iPhone USB lease overlaps the downstream network"
    return ResolvedUpstream(
        connection=IPHONE_USB,
        interface=interface,
        address=str(upstream),
        gateway=str(peer),
    ), None
