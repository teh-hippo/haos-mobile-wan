from __future__ import annotations

from .faults import FaultSpec

PERSISTENT_OWNERSHIP_STATE_INVALID = FaultSpec(
    id="persistent_ownership_state_invalid",
    translation_key="state_invalid",
    summary="Saved gateway ownership state is invalid",
    template="Persistent ownership state is invalid",
)

MANAGEMENT_BASELINE_MISMATCH = FaultSpec(
    id="management_baseline_mismatch",
    translation_key="host_configuration",
    summary="The management baseline no longer matches the configured host state",
    template="Management interface/address baseline does not match",
)

MANAGEMENT_INTERFACE_UNAVAILABLE = FaultSpec(
    id="management_interface_unavailable",
    translation_key="host_configuration",
    summary="The management interface is unavailable",
    template="Management interface is unavailable",
)

IPV4_FORWARDING_DISABLED = FaultSpec(
    id="ipv4_forwarding_disabled",
    translation_key="host_configuration",
    summary="Host IPv4 forwarding is disabled",
    template="Host IPv4 forwarding is not enabled",
)

IPV4_FORWARDING_UNVERIFIED = FaultSpec(
    id="ipv4_forwarding_unverified",
    translation_key="host_configuration",
    summary="The gateway could not verify host IPv4 forwarding",
    template="Cannot verify host IPv4 forwarding",
)

IPTABLES_BACKEND_MISMATCH = FaultSpec(
    id="iptables_backend_mismatch",
    translation_key="host_configuration",
    summary="iptables is not using the nf_tables backend",
    template="iptables is not using the nf_tables backend",
)

DOCKER_USER_MISSING = FaultSpec(
    id="docker_user_missing",
    translation_key="host_configuration",
    summary="The Docker DOCKER-USER chain is missing",
    template="Docker DOCKER-USER chain is missing",
)

FIREWALL_BACKEND_UNAVAILABLE = FaultSpec(
    id="firewall_backend_unavailable",
    translation_key="host_configuration",
    summary="The gateway could not inspect the host firewall backend",
    template="Cannot inspect the host firewall backend",
)

UPSTREAM_INTERFACE_UNAVAILABLE = FaultSpec(
    id="upstream_interface_unavailable",
    summary="The upstream interface is unavailable",
    transient=True,
    template="Upstream interface is unavailable",
)

UPSTREAM_INTERFACE_INACTIVE = FaultSpec(
    id="upstream_interface_inactive",
    summary="The upstream interface is not active",
    transient=True,
    template="Upstream interface/address is not active",
)

HOTSPOT_ADAPTER_DISABLED = FaultSpec(
    id="hotspot_adapter_disabled",
    translation_key="hotspot_adapter_disabled",
    summary="The hotspot Wi-Fi adapter is disabled",
    template="Hotspot Wi-Fi adapter is disabled",
)

HOTSPOT_NOT_ASSOCIATED = FaultSpec(
    id="hotspot_not_associated",
    translation_key="hotspot_not_associated",
    summary="The hotspot Wi-Fi adapter is enabled but has not associated with the phone",
    transient=True,
    template="Hotspot Wi-Fi is enabled but not associated",
)

MANAGEMENT_DEFAULT_ROUTE_MISSING = FaultSpec(
    id="management_default_route_missing",
    translation_key="host_configuration",
    summary="The management interface is not the main default route",
    template="Management interface is not the main default route",
)

UPSTREAM_DEFAULT_ROUTE_PRESENT = FaultSpec(
    id="upstream_default_route_present",
    translation_key="host_configuration",
    summary="The mobile upstream still has a main default route",
    template="Mobile upstream has a main-table default route",
)

DEFAULT_ROUTES_UNAVAILABLE = FaultSpec(
    id="default_routes_unavailable",
    translation_key="host_configuration",
    summary="The gateway could not inspect the main default routes",
    template="Cannot inspect main-table default routes",
)

DOWNSTREAM_MISSING = FaultSpec(
    id="downstream_missing",
    translation_key="downstream_configuration",
    summary="The configured downstream NIC is not present",
    template="Configured downstream NIC is not present",
)

DOWNSTREAM_MISSING_2 = FaultSpec(
    id="downstream_missing",
    translation_key="downstream_configuration",
    summary="A USB Ethernet downstream adapter is not present",
    template="USB Ethernet downstream is not present",
)

DOWNSTREAM_AMBIGUOUS = FaultSpec(
    id="downstream_ambiguous",
    translation_key="downstream_configuration",
    summary="More than one eligible USB Ethernet adapter is attached",
    template="Multiple USB Ethernet adapters detected; set downstream_mac",
)

DOWNSTREAM_INTERFACE_OVERLAP = FaultSpec(
    id="downstream_interface_overlap",
    translation_key="downstream_configuration",
    summary="The downstream NIC must differ from the management and upstream interfaces",
    template="Downstream NIC must differ from management and upstream interfaces",
)

DOWNSTREAM_HOST_MANAGED = FaultSpec(
    id="downstream_host_managed",
    translation_key="downstream_configuration",
    summary="The downstream adapter has host-managed IPv4 configuration",
    template="Downstream interface has host-managed IPv4 addresses",
)

DOWNSTREAM_INACTIVE = FaultSpec(
    id="downstream_inactive",
    translation_key="downstream_configuration",
    summary="The app-owned downstream address is unavailable",
    template="App-owned downstream address is unavailable",
)

DOWNSTREAM_ADDRESS_CONFLICT = FaultSpec(
    id="downstream_address_conflict",
    translation_key="downstream_configuration",
    summary="The downstream adapter has unexpected IPv4 addresses",
    template="Downstream interface has unexpected IPv4 addresses",
)

DOWNSTREAM_UNAVAILABLE = FaultSpec(
    id="downstream_unavailable",
    translation_key="downstream_configuration",
    summary="The downstream interface is unavailable",
    template="Downstream interface is unavailable",
)

DOWNSTREAM_IPV6_ACTIVE = FaultSpec(
    id="downstream_ipv6_active",
    translation_key="downstream_configuration",
    summary="IPv6 is active on the downstream NIC",
    template="IPv6 is active on downstream NIC",
)

DOWNSTREAM_IPV6_UNVERIFIED = FaultSpec(
    id="downstream_ipv6_unverified",
    translation_key="downstream_configuration",
    summary="The gateway could not verify downstream IPv6 state",
    template="Cannot verify downstream IPv6 state",
)

UPSTREAM_IPV6_ACTIVE = FaultSpec(
    id="upstream_ipv6_active",
    translation_key="host_configuration",
    summary="IPv6 is active on the mobile upstream",
    template="IPv6 is active on mobile upstream",
)

UPSTREAM_IPV6_UNVERIFIED = FaultSpec(
    id="upstream_ipv6_unverified",
    translation_key="host_configuration",
    summary="The gateway could not verify mobile upstream IPv6 state",
    template="Cannot verify upstream IPv6 state",
)

POLICY_OWNERSHIP_UNAVAILABLE = FaultSpec(
    id="policy_ownership_unavailable",
    translation_key="policy_configuration",
    summary="The gateway could not inspect policy-routing ownership",
    template="Cannot inspect policy-routing ownership",
)

HOST_FAULTS: tuple[FaultSpec, ...] = (
    PERSISTENT_OWNERSHIP_STATE_INVALID,
    MANAGEMENT_BASELINE_MISMATCH,
    MANAGEMENT_INTERFACE_UNAVAILABLE,
    IPV4_FORWARDING_DISABLED,
    IPV4_FORWARDING_UNVERIFIED,
    IPTABLES_BACKEND_MISMATCH,
    DOCKER_USER_MISSING,
    FIREWALL_BACKEND_UNAVAILABLE,
    UPSTREAM_INTERFACE_UNAVAILABLE,
    UPSTREAM_INTERFACE_INACTIVE,
    HOTSPOT_ADAPTER_DISABLED,
    HOTSPOT_NOT_ASSOCIATED,
    MANAGEMENT_DEFAULT_ROUTE_MISSING,
    UPSTREAM_DEFAULT_ROUTE_PRESENT,
    DEFAULT_ROUTES_UNAVAILABLE,
    DOWNSTREAM_MISSING,
    DOWNSTREAM_MISSING_2,
    DOWNSTREAM_AMBIGUOUS,
    DOWNSTREAM_INTERFACE_OVERLAP,
    DOWNSTREAM_HOST_MANAGED,
    DOWNSTREAM_INACTIVE,
    DOWNSTREAM_ADDRESS_CONFLICT,
    DOWNSTREAM_UNAVAILABLE,
    DOWNSTREAM_IPV6_ACTIVE,
    DOWNSTREAM_IPV6_UNVERIFIED,
    UPSTREAM_IPV6_ACTIVE,
    UPSTREAM_IPV6_UNVERIFIED,
    POLICY_OWNERSHIP_UNAVAILABLE,
)
