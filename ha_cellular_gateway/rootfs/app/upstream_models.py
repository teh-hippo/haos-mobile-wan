from __future__ import annotations

import ipaddress
from dataclasses import dataclass

from .config import GatewayConfig


@dataclass(frozen=True)
class ResolvedUpstream:
    mode: str
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
        mode=config.upstream_mode,
        interface=config.upstream_interface,
        address=config.upstream_address,
        gateway=config.upstream_gateway,
    )
