from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from .config import GatewayConfig
from .errors import GatewayError
from .firewall import Firewall
from .policy import PolicyRouting
from .upstream import ResolvedUpstream


RunCommand = Callable[..., subprocess.CompletedProcess[str]]


class SafetyInspector:
    def __init__(
        self,
        config: GatewayConfig,
        run: RunCommand,
        read_text: Callable[[Path], str],
        firewall: Firewall,
        policy: PolicyRouting,
    ) -> None:
        self.config = config
        self.run = run
        self.read_text = read_text
        self.firewall = firewall
        self.policy = policy

    def _read_json(self, *args: str) -> object:
        result = self.run(*args)
        return json.loads(result.stdout or "[]")

    def interface_addresses(self, interface: str, family: int = 4) -> set[str]:
        data = self._read_json(
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
            for address in item.get("addr_info", []):
                expected_family = "inet" if family == 4 else "inet6"
                if address.get("family") == expected_family:
                    addresses.add(
                        f"{address['local']}/{address['prefixlen']}"
                    )
        return addresses

    def find_downstream(self) -> str | None:
        if not self.config.downstream_mac:
            return None
        root = Path("/sys/class/net")
        if not root.exists():
            return None
        for interface in root.iterdir():
            try:
                address = self.read_text(interface / "address").strip().lower()
            except OSError:
                continue
            if address == self.config.downstream_mac:
                return interface.name
        return None

    def _main_default_interfaces(self) -> set[str]:
        routes = self._read_json(
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

    def errors(
        self,
        downstream: str | None = None,
        *,
        upstream: ResolvedUpstream | None = None,
        upstream_errors: list[str] | None = None,
        state_error: str | None = None,
    ) -> list[str]:
        downstream = downstream or self.find_downstream()
        errors: list[str] = []
        current_upstream = upstream
        upstream_interface = (
            current_upstream.interface if current_upstream else self.config.upstream_interface
        )
        if state_error:
            errors.append(state_error)
        if upstream_errors:
            errors.extend(upstream_errors)

        try:
            management_addresses = self.interface_addresses(
                self.config.management_interface
            )
            if self.config.management_address not in management_addresses:
                errors.append("Management interface/address baseline does not match")
        except (GatewayError, OSError, subprocess.SubprocessError, ValueError):
            errors.append("Management interface is unavailable")

        try:
            if self._ip_forward() != 1:
                errors.append("Host IPv4 forwarding is not enabled")
        except (OSError, ValueError):
            errors.append("Cannot verify host IPv4 forwarding")

        for interface in (
            "all",
            "default",
            self.config.management_interface,
            upstream_interface,
        ):
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
            if self.config.management_interface not in default_interfaces:
                errors.append("Management interface is not the main default route")
            unexpected_defaults = default_interfaces - {
                self.config.management_interface
            }
            if unexpected_defaults:
                errors.append(
                    "Unexpected main-table default route: "
                    + ",".join(sorted(unexpected_defaults))
                )
            if upstream_interface in default_interfaces:
                errors.append("Mobile upstream has a main-table default route")
        except (GatewayError, OSError, subprocess.SubprocessError, ValueError):
            errors.append("Cannot inspect main-table default routes")

        if downstream is None:
            errors.append("Configured downstream NIC is not present")
        else:
            errors.extend(self._downstream_errors(downstream, upstream_interface))
            try:
                errors.extend(self.policy.conflicts(downstream, current_upstream))
            except (
                GatewayError,
                OSError,
                subprocess.SubprocessError,
                ValueError,
            ):
                errors.append("Cannot inspect policy-routing ownership")

        try:
            if self.interface_addresses(
                upstream_interface,
                family=6,
            ):
                errors.append("IPv6 is active on mobile upstream")
        except (GatewayError, OSError, subprocess.SubprocessError, ValueError):
            errors.append("Cannot verify upstream IPv6 state")

        return errors

    def _downstream_errors(self, downstream: str, upstream_interface: str) -> list[str]:
        errors: list[str] = []
        if downstream in {
            self.config.management_interface,
            upstream_interface,
        }:
            errors.append(
                "Downstream NIC must differ from management and upstream interfaces"
            )
        try:
            downstream_addresses = self.interface_addresses(downstream)
            if self.config.downstream_address not in downstream_addresses:
                errors.append("Downstream interface/address is not active")
            if self._rp_filter(downstream) == 1:
                errors.append("Strict rp_filter is enabled on downstream NIC")
        except (GatewayError, OSError, subprocess.SubprocessError, ValueError):
            errors.append("Downstream interface is unavailable")
        try:
            if self.interface_addresses(downstream, family=6):
                errors.append("IPv6 is active on downstream NIC")
        except (GatewayError, OSError, subprocess.SubprocessError, ValueError):
            errors.append("Cannot verify downstream IPv6 state")
        return errors
