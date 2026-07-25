from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from .errors import GatewayError
from .fault_catalogue_host import (
    DEFAULT_ROUTES_UNAVAILABLE,
    DOCKER_USER_MISSING,
    DOWNSTREAM_INTERFACE_OVERLAP,
    DOWNSTREAM_IPV6_ACTIVE,
    DOWNSTREAM_IPV6_UNVERIFIED,
    DOWNSTREAM_UNAVAILABLE,
    FIREWALL_BACKEND_UNAVAILABLE,
    IPTABLES_BACKEND_MISMATCH,
    IPV4_FORWARDING_DISABLED,
    IPV4_FORWARDING_UNVERIFIED,
    MANAGEMENT_BASELINE_MISMATCH,
    MANAGEMENT_DEFAULT_ROUTE_MISSING,
    MANAGEMENT_INTERFACE_UNAVAILABLE,
    POLICY_OWNERSHIP_UNAVAILABLE,
    UPSTREAM_DEFAULT_ROUTE_PRESENT,
    UPSTREAM_INTERFACE_INACTIVE,
    UPSTREAM_INTERFACE_UNAVAILABLE,
    UPSTREAM_IPV6_ACTIVE,
    UPSTREAM_IPV6_UNVERIFIED,
)
from .fault_catalogue_rules import (
    RP_FILTER_UNAVAILABLE,
    STRICT_RP_FILTER_ENABLED,
    UNEXPECTED_DEFAULT_ROUTE,
)
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
        return [MANAGEMENT_INTERFACE_UNAVAILABLE.text]
    try:
        if management.address not in inspector.interface_addresses(
            management.interface
        ):
            return [MANAGEMENT_BASELINE_MISMATCH.text]
    except OPERATION_ERRORS:
        return [MANAGEMENT_INTERFACE_UNAVAILABLE.text]
    return []


def ip_forward_errors(inspector: SafetyInspector) -> list[str]:
    try:
        if inspector.ip_forward() != 1:
            return [IPV4_FORWARDING_DISABLED.text]
    except (OSError, ValueError):
        return [IPV4_FORWARDING_UNVERIFIED.text]
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
                errors.append(STRICT_RP_FILTER_ENABLED.render(interface=interface))
        except (OSError, ValueError):
            errors.append(RP_FILTER_UNAVAILABLE.render(interface=interface))
    return errors


def firewall_errors(inspector: SafetyInspector) -> list[str]:
    errors: list[str] = []
    try:
        if not inspector.firewall.backend_ok():
            errors.append(IPTABLES_BACKEND_MISMATCH.text)
        if not inspector.firewall.chain_exists("iptables", "DOCKER-USER"):
            errors.append(DOCKER_USER_MISSING.text)
    except (GatewayError, OSError, subprocess.SubprocessError):
        errors.append(FIREWALL_BACKEND_UNAVAILABLE.text)
    return errors


def upstream_availability_errors(
    inspector: SafetyInspector, current_upstream: ResolvedUpstream | None
) -> list[str]:
    try:
        if current_upstream is None:
            return [UPSTREAM_INTERFACE_UNAVAILABLE.text]
        upstream_addresses = inspector.interface_addresses(current_upstream.interface)
        if current_upstream.address not in upstream_addresses:
            return [UPSTREAM_INTERFACE_INACTIVE.text]
    except OPERATION_ERRORS:
        return [UPSTREAM_INTERFACE_UNAVAILABLE.text]
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
                errors.append(MANAGEMENT_DEFAULT_ROUTE_MISSING.text)
            unexpected_defaults = default_interfaces - {management_interface}
            if unexpected_defaults:
                errors.append(
                    UNEXPECTED_DEFAULT_ROUTE.render(
                        detail=",".join(sorted(unexpected_defaults))
                    )
                )
        if upstream_interface and upstream_interface in default_interfaces:
            errors.append(UPSTREAM_DEFAULT_ROUTE_PRESENT.text)
    except OPERATION_ERRORS:
        errors.append(DEFAULT_ROUTES_UNAVAILABLE.text)
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
        return [POLICY_OWNERSHIP_UNAVAILABLE.text]


def upstream_ipv6_errors(
    inspector: SafetyInspector, upstream_interface: str | None
) -> list[str]:
    if not upstream_interface:
        return []
    try:
        if inspector.has_non_link_local_ipv6(upstream_interface):
            return [UPSTREAM_IPV6_ACTIVE.text]
    except OPERATION_ERRORS:
        return [UPSTREAM_IPV6_UNVERIFIED.text]
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
        errors.append(DOWNSTREAM_INTERFACE_OVERLAP.text)
    try:
        errors.extend(
            inspector.downstream.address_errors(
                downstream,
                owned=address_owned,
            )
        )
        if inspector.rp_filter(downstream) == 1:
            errors.append(STRICT_RP_FILTER_ENABLED.render(interface="downstream NIC"))
    except OPERATION_ERRORS:
        errors.append(DOWNSTREAM_UNAVAILABLE.text)
    try:
        if inspector.has_non_link_local_ipv6(downstream):
            errors.append(DOWNSTREAM_IPV6_ACTIVE.text)
    except OPERATION_ERRORS:
        errors.append(DOWNSTREAM_IPV6_UNVERIFIED.text)
    return errors
