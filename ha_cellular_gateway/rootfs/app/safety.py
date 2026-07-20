from __future__ import annotations

import ipaddress
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from . import safety_checks as checks
from .command import RunCommand, run_json
from .config import GatewayConfig
from .downstream import DownstreamInterface
from .firewall import Firewall
from .policy import PolicyRouting
from .upstream_models import ResolvedUpstream

if TYPE_CHECKING:
    from .management import ManagementBaseline


class SafetyInspector:
    def __init__(
        self,
        config: GatewayConfig,
        run: RunCommand,
        read_text: Callable[[Path], str],
        firewall: Firewall,
        policy: PolicyRouting,
        downstream: DownstreamInterface,
    ) -> None:
        self.config = config
        self.run = run
        self.read_text = read_text
        self.firewall = firewall
        self.policy = policy
        self.downstream = downstream

    def interface_addresses(self, interface: str, family: int = 4) -> set[str]:
        return self.downstream.addresses(interface, family=family)

    def find_downstream(self, management_interface: str | None = None) -> str | None:
        return self.downstream.find(management_interface)

    def main_default_interfaces(self) -> set[str]:
        routes = run_json(
            self.run,
            "ip",
            "-4",
            "-j",
            "route",
            "show",
            "table",
            "main",
            "default",
        )
        if not isinstance(routes, list):
            return set()
        return {route["dev"] for route in routes if "dev" in route}

    def rp_filter(self, interface: str) -> int:
        path = Path(f"/proc/sys/net/ipv4/conf/{interface}/rp_filter")
        return int(self.read_text(path).strip())

    def ip_forward(self) -> int:
        return int(self.read_text(Path("/proc/sys/net/ipv4/ip_forward")).strip())

    def has_non_link_local_ipv6(self, interface: str) -> bool:
        return any(
            not ipaddress.ip_interface(address).ip.is_link_local
            for address in self.interface_addresses(interface, family=6)
        )

    def errors(
        self,
        downstream: str | None = None,
        *,
        management: ManagementBaseline | None = None,
        upstream: ResolvedUpstream | None = None,
        upstream_errors: list[str] | None = None,
        state_error: str | None = None,
        downstream_address_owned: bool = False,
    ) -> list[str]:
        """Run every host safety phase in fail-closed order."""
        management_interface = management.interface if management else None
        downstream = downstream or self.find_downstream(management_interface)
        current_upstream = upstream
        upstream_interface = checks.resolve_upstream_interface(self, current_upstream)

        errors: list[str] = []
        errors.extend(checks.prior_errors(state_error, upstream_errors))
        errors.extend(checks.management_errors(self, management))
        errors.extend(checks.ip_forward_errors(self))
        errors.extend(
            checks.rp_filter_errors(self, management_interface, upstream_interface)
        )
        errors.extend(checks.firewall_errors(self))
        errors.extend(checks.upstream_availability_errors(self, current_upstream))
        errors.extend(
            checks.default_route_errors(self, management_interface, upstream_interface)
        )
        errors.extend(
            checks.downstream_section_errors(
                self,
                downstream,
                upstream_interface,
                management_interface=management_interface,
                downstream_address_owned=downstream_address_owned,
                current_upstream=current_upstream,
            )
        )
        errors.extend(checks.upstream_ipv6_errors(self, upstream_interface))
        return errors
