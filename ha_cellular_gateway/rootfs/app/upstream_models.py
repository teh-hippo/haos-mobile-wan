from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from .config import GatewayConfig
from .const import WIFI_HOTSPOT


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
