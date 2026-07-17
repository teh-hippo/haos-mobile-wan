from __future__ import annotations

import ipaddress
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from .command import RunCommand, run_json
from .config import GatewayConfig
from .errors import GatewayError
from .firewall import Firewall
from .downstream import DownstreamInterface
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

    def _main_default_interfaces(self) -> set[str]:
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
        return {route["dev"] for route in routes if "dev" in route}

    def _rp_filter(self, interface: str) -> int:
        path = Path(f"/proc/sys/net/ipv4/conf/{interface}/rp_filter")
        return int(self.read_text(path).strip())

    def _ip_forward(self) -> int:
        return int(
            self.read_text(Path("/proc/sys/net/ipv4/ip_forward")).strip()
        )

    def _has_non_link_local_ipv6(self, interface: str) -> bool:
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
        management_interface = management.interface if management else None
        downstream = downstream or self.find_downstream(management_interface)
        errors: list[str] = []
        current_upstream = upstream
        upstream_interface = (
            current_upstream.interface
            if current_upstream
            else self.config.upstream_interface
            if self.config.uses_wifi
            else None
        )
        if state_error:
            errors.append(state_error)
        if upstream_errors:
            errors.extend(upstream_errors)

        if management is None:
            errors.append("Management interface is unavailable")
        else:
            try:
                if management.address not in self.interface_addresses(
                    management.interface
                ):
                    errors.append(
                        "Management interface/address baseline does not match"
                    )
            except (GatewayError, OSError, subprocess.SubprocessError, ValueError):
                errors.append("Management interface is unavailable")

        try:
            if self._ip_forward() != 1:
                errors.append("Host IPv4 forwarding is not enabled")
        except (OSError, ValueError):
            errors.append("Cannot verify host IPv4 forwarding")

        interfaces = ["all", "default"]
        if management_interface:
            interfaces.append(management_interface)
        if upstream_interface:
            interfaces.append(upstream_interface)
        for interface in interfaces:
            try:
                if self._rp_filter(interface) == 1:
                    errors.append(f"Strict rp_filter is enabled on {interface}")
            except (OSError, ValueError):
                errors.append(f"Cannot read rp_filter for {interface}")

        try:
            if not self.firewall.backend_ok():
                errors.append("iptables is not using the nf_tables backend")
            if not self.firewall.chain_exists("iptables", "DOCKER-USER"):
                errors.append("Docker DOCKER-USER chain is missing")
        except (GatewayError, OSError, subprocess.SubprocessError):
            errors.append("Cannot inspect the host firewall backend")

        try:
            if current_upstream is None:
                errors.append("Upstream interface is unavailable")
            else:
                upstream_addresses = self.interface_addresses(current_upstream.interface)
                if current_upstream.address not in upstream_addresses:
                    errors.append("Upstream interface/address is not active")
        except (GatewayError, OSError, subprocess.SubprocessError, ValueError):
            errors.append("Upstream interface is unavailable")

        try:
            default_interfaces = self._main_default_interfaces()
            if management_interface:
                if management_interface not in default_interfaces:
                    errors.append("Management interface is not the main default route")
                unexpected_defaults = default_interfaces - {management_interface}
                if unexpected_defaults:
                    errors.append(
                        "Unexpected main-table default route: "
                        + ",".join(sorted(unexpected_defaults))
                    )
            if upstream_interface and upstream_interface in default_interfaces:
                errors.append("Mobile upstream has a main-table default route")
        except (GatewayError, OSError, subprocess.SubprocessError, ValueError):
            errors.append("Cannot inspect main-table default routes")

        if downstream is None:
            errors.append(self.downstream.selection_error(management_interface))
        else:
            errors.extend(
                self._downstream_errors(
                    downstream,
                    upstream_interface,
                    management_interface=management_interface,
                    address_owned=downstream_address_owned,
                )
            )
            try:
                if current_upstream is not None:
                    errors.extend(
                        self.policy.conflicts(
                            downstream,
                            current_upstream,
                        )
                    )
            except (
                GatewayError,
                OSError,
                subprocess.SubprocessError,
                ValueError,
            ):
                errors.append("Cannot inspect policy-routing ownership")

        try:
            if (
                upstream_interface
                and self._has_non_link_local_ipv6(upstream_interface)
            ):
                errors.append("IPv6 is active on mobile upstream")
        except (GatewayError, OSError, subprocess.SubprocessError, ValueError):
            errors.append("Cannot verify upstream IPv6 state")

        return errors

    def _downstream_errors(
        self,
        downstream: str,
        upstream_interface: str | None,
        *,
        management_interface: str | None,
        address_owned: bool,
    ) -> list[str]:
        errors: list[str] = []
        if downstream in {management_interface, upstream_interface}:
            errors.append(
                "Downstream NIC must differ from management and upstream interfaces"
            )
        try:
            errors.extend(
                self.downstream.address_errors(
                    downstream,
                    owned=address_owned,
                )
            )
            if self._rp_filter(downstream) == 1:
                errors.append("Strict rp_filter is enabled on downstream NIC")
        except (GatewayError, OSError, subprocess.SubprocessError, ValueError):
            errors.append("Downstream interface is unavailable")
        try:
            if self._has_non_link_local_ipv6(downstream):
                errors.append("IPv6 is active on downstream NIC")
        except (GatewayError, OSError, subprocess.SubprocessError, ValueError):
            errors.append("Cannot verify downstream IPv6 state")
        return errors
