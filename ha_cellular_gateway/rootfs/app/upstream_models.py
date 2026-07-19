from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .config import GatewayConfig
from .const import IPHONE_USB, WIFI_HOTSPOT

if TYPE_CHECKING:
    from .management import ManagementBaseline


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
    management: ManagementBaseline | None = None,
    *,
    connection: str = IPHONE_USB,
    label: str = "iPhone USB",
) -> tuple[ResolvedUpstream | None, str | None]:
    try:
        upstream = ipaddress.ip_interface(address)
        peer = ipaddress.ip_address(gateway)
        downstream = ipaddress.ip_interface(config.downstream_address)
        management_network = (
            ipaddress.ip_interface(management.address).network
            if management is not None
            else None
        )
    except ValueError as err:
        return None, f"{label} lease is invalid: {err}"
    if upstream.version != 4 or peer.version != 4:
        return None, f"{label} lease must use IPv4"
    if upstream.ip in {
        upstream.network.network_address,
        upstream.network.broadcast_address,
    }:
        return None, f"{label} lease address is not a usable host address"
    if peer not in upstream.network:
        return None, f"{label} lease gateway is outside the lease subnet"
    if peer in {
        upstream.ip,
        upstream.network.network_address,
        upstream.network.broadcast_address,
    }:
        return None, f"{label} lease gateway is not a usable peer address"
    if management_network is not None and upstream.network.overlaps(
        management_network
    ):
        return None, f"{label} lease overlaps the management network"
    if upstream.network.overlaps(downstream.network):
        return None, f"{label} lease overlaps the downstream network"
    return ResolvedUpstream(
        connection=connection,
        interface=interface,
        address=str(upstream),
        gateway=str(peer),
    ), None
