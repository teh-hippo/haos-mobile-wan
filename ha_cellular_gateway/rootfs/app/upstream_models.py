from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from .config import GatewayConfig
from .const import IPHONE_USB, WIFI_HOTSPOT


@dataclass(frozen=True)
class ResolvedUpstream:
    connection: str
    interface: str
    address: str
    gateway: str

    @property
    def ip(self) -> str:
        return str(ipaddress.ip_interface(self.address).ip)

    @property
    def network(self) -> str:
        return str(ipaddress.ip_interface(self.address).network)


def configured_upstream(config: GatewayConfig) -> ResolvedUpstream:
    return ResolvedUpstream(
        connection=WIFI_HOTSPOT,
        interface=config.upstream_interface,
        address=config.upstream_address,
        gateway=config.upstream_gateway,
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
