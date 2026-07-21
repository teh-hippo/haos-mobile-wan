from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from .errors import GatewayError
from .upstream_models import ResolvedUpstream

if TYPE_CHECKING:
    from .management import ManagementBaseline
    from .safety import SafetyInspector

OPERATION_ERRORS = (GatewayError, OSError, subprocess.SubprocessError, ValueError)


def resolve_upstream_interface(
    inspector: SafetyInspector, upstream: ResolvedUpstream | None
) -> str | None:
    if upstream:
        return upstream.interface
    if inspector.config.uses_wifi:
        return inspector.config.upstream_interface
    return None


def prior_errors(
    state_error: str | None, upstream_errors: list[str] | None
) -> list[str]:
    errors: list[str] = []
    if state_error:
        errors.append(state_error)
    if upstream_errors:
        errors.extend(upstream_errors)
    return errors


def management_errors(
    inspector: SafetyInspector, management: ManagementBaseline | None
) -> list[str]:
    if management is None:
        return ["Management interface is unavailable"]
    try:
        if management.address not in inspector.interface_addresses(
            management.interface
        ):
            return ["Management interface/address baseline does not match"]
    except OPERATION_ERRORS:
        return ["Management interface is unavailable"]
    return []


def ip_forward_errors(inspector: SafetyInspector) -> list[str]:
    try:
        if inspector.ip_forward() != 1:
            return ["Host IPv4 forwarding is not enabled"]
    except (OSError, ValueError):
        return ["Cannot verify host IPv4 forwarding"]
    return []


def rp_filter_errors(
    inspector: SafetyInspector,
    management_interface: str | None,
    upstream_interface: str | None,
) -> list[str]:
    interfaces = ["all", "default"]
    if management_interface:
        interfaces.append(management_interface)
    if upstream_interface:
        interfaces.append(upstream_interface)
    errors: list[str] = []
    for interface in interfaces:
        try:
            if inspector.rp_filter(interface) == 1:
                errors.append(f"Strict rp_filter is enabled on {interface}")
        except (OSError, ValueError):
            errors.append(f"Cannot read rp_filter for {interface}")
    return errors


def firewall_errors(inspector: SafetyInspector) -> list[str]:
    errors: list[str] = []
    try:
        if not inspector.firewall.backend_ok():
            errors.append("iptables is not using the nf_tables backend")
        if not inspector.firewall.chain_exists("iptables", "DOCKER-USER"):
            errors.append("Docker DOCKER-USER chain is missing")
    except (GatewayError, OSError, subprocess.SubprocessError):
        errors.append("Cannot inspect the host firewall backend")
    return errors


def upstream_availability_errors(
    inspector: SafetyInspector, current_upstream: ResolvedUpstream | None
) -> list[str]:
    try:
        if current_upstream is None:
            return ["Upstream interface is unavailable"]
        upstream_addresses = inspector.interface_addresses(current_upstream.interface)
        if current_upstream.address not in upstream_addresses:
            return ["Upstream interface/address is not active"]
    except OPERATION_ERRORS:
        return ["Upstream interface is unavailable"]
    return []


def default_route_errors(
    inspector: SafetyInspector,
    management_interface: str | None,
    upstream_interface: str | None,
) -> list[str]:
    errors: list[str] = []
    try:
        default_interfaces = inspector.main_default_interfaces()
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
    except OPERATION_ERRORS:
        errors.append("Cannot inspect main-table default routes")
    return errors


def downstream_section_errors(
    inspector: SafetyInspector,
    downstream: str | None,
    upstream_interface: str | None,
    *,
    management_interface: str | None,
    downstream_address_owned: bool,
    current_upstream: ResolvedUpstream | None,
) -> list[str]:
    if downstream is None:
        return [inspector.downstream.selection_error(management_interface)]
    errors = downstream_errors(
        inspector,
        downstream,
        upstream_interface,
        management_interface=management_interface,
        address_owned=downstream_address_owned,
    )
    errors.extend(policy_conflict_errors(inspector, downstream, current_upstream))
    return errors


def policy_conflict_errors(
    inspector: SafetyInspector,
    downstream: str,
    current_upstream: ResolvedUpstream | None,
) -> list[str]:
    if current_upstream is None:
        return []
    try:
        return inspector.policy.conflicts(downstream, current_upstream)
    except OPERATION_ERRORS:
        return ["Cannot inspect policy-routing ownership"]


def upstream_ipv6_errors(
    inspector: SafetyInspector, upstream_interface: str | None
) -> list[str]:
    if not upstream_interface:
        return []
    try:
        if inspector.has_non_link_local_ipv6(upstream_interface):
            return ["IPv6 is active on mobile upstream"]
    except OPERATION_ERRORS:
        return ["Cannot verify upstream IPv6 state"]
    return []


def downstream_errors(
    inspector: SafetyInspector,
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
            inspector.downstream.address_errors(
                downstream,
                owned=address_owned,
            )
        )
        if inspector.rp_filter(downstream) == 1:
            errors.append("Strict rp_filter is enabled on downstream NIC")
    except OPERATION_ERRORS:
        errors.append("Downstream interface is unavailable")
    try:
        if inspector.has_non_link_local_ipv6(downstream):
            errors.append("IPv6 is active on downstream NIC")
    except OPERATION_ERRORS:
        errors.append("Cannot verify downstream IPv6 state")
    return errors
