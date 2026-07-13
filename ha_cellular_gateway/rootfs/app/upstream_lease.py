from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from pathlib import Path

from .config import GatewayConfig
from .upstream_models import ResolvedUpstream


@dataclass(frozen=True)
class DynamicLease:
    interface: str
    address: str | None
    gateway: str | None
    has_default_route: bool


def load_app_lease(path: Path, interface: str) -> tuple[str, str] | None:
    if not path.exists():
        return None
    try:
        lease = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(lease, dict)
        or lease.get("interface") != interface
        or "address" not in lease
        or "gateway" not in lease
    ):
        return None
    owner = str(lease.get("owner", "app"))
    if owner != "app":
        return None
    return str(lease["address"]), str(lease["gateway"])


def inspect_external_lease(
    addresses: object,
    routes: object,
    interface: str,
) -> DynamicLease:
    address: str | None = None
    gateway: str | None = None
    has_default_route = False
    for item in addresses if isinstance(addresses, list) else []:
        for entry in item.get("addr_info", []):
            if entry.get("family") == "inet":
                address = f"{entry['local']}/{entry['prefixlen']}"
                break
        if address:
            break
    for route in routes if isinstance(routes, list) else []:
        if route.get("dev") != interface or route.get("dst") != "default":
            continue
        has_default_route = True
        if route.get("gateway"):
            gateway = str(route["gateway"])
            break
    return DynamicLease(
        interface=interface,
        address=address,
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
        mode=config.upstream_mode,
        interface=interface,
        address=str(upstream),
        gateway=str(peer),
    ), None
