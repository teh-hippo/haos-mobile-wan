"""Faults whose reported text is fixed, covering host, downstream and policy."""

from __future__ import annotations

from .faults import FaultSpec

HOST_FAULTS: tuple[FaultSpec, ...] = (
    FaultSpec(
        id="persistent_ownership_state_invalid",
        translation_key="state_invalid",
        summary="Saved gateway ownership state is invalid",
        exact=("Persistent ownership state is invalid",),
    ),
    FaultSpec(
        id="management_baseline_mismatch",
        translation_key="host_configuration",
        summary="The management baseline no longer matches the configured host state",
        exact=("Management interface/address baseline does not match",),
    ),
    FaultSpec(
        id="management_interface_unavailable",
        translation_key="host_configuration",
        summary="The management interface is unavailable",
        exact=("Management interface is unavailable",),
    ),
    FaultSpec(
        id="ipv4_forwarding_disabled",
        translation_key="host_configuration",
        summary="Host IPv4 forwarding is disabled",
        exact=("Host IPv4 forwarding is not enabled",),
    ),
    FaultSpec(
        id="ipv4_forwarding_unverified",
        translation_key="host_configuration",
        summary="The gateway could not verify host IPv4 forwarding",
        exact=("Cannot verify host IPv4 forwarding",),
    ),
    FaultSpec(
        id="iptables_backend_mismatch",
        translation_key="host_configuration",
        summary="iptables is not using the nf_tables backend",
        exact=("iptables is not using the nf_tables backend",),
    ),
    FaultSpec(
        id="docker_user_missing",
        translation_key="host_configuration",
        summary="The Docker DOCKER-USER chain is missing",
        exact=("Docker DOCKER-USER chain is missing",),
    ),
    FaultSpec(
        id="firewall_backend_unavailable",
        translation_key="host_configuration",
        summary="The gateway could not inspect the host firewall backend",
        exact=("Cannot inspect the host firewall backend",),
    ),
    FaultSpec(
        id="upstream_interface_unavailable",
        summary="The upstream interface is unavailable",
        transient=True,
        exact=("Upstream interface is unavailable",),
    ),
    FaultSpec(
        id="upstream_interface_inactive",
        summary="The upstream interface is not active",
        transient=True,
        exact=("Upstream interface/address is not active",),
    ),
    FaultSpec(
        id="hotspot_adapter_disabled",
        translation_key="hotspot_adapter_disabled",
        summary="The hotspot Wi-Fi adapter is disabled",
        exact=("Hotspot Wi-Fi adapter is disabled",),
    ),
    FaultSpec(
        id="hotspot_not_associated",
        translation_key="hotspot_not_associated",
        summary="The hotspot Wi-Fi adapter is enabled but has not associated with the phone",
        transient=True,
        exact=("Hotspot Wi-Fi is enabled but not associated",),
    ),
    FaultSpec(
        id="management_default_route_missing",
        translation_key="host_configuration",
        summary="The management interface is not the main default route",
        exact=("Management interface is not the main default route",),
    ),
    FaultSpec(
        id="upstream_default_route_present",
        translation_key="host_configuration",
        summary="The mobile upstream still has a main default route",
        exact=("Mobile upstream has a main-table default route",),
    ),
    FaultSpec(
        id="default_routes_unavailable",
        translation_key="host_configuration",
        summary="The gateway could not inspect the main default routes",
        exact=("Cannot inspect main-table default routes",),
    ),
    FaultSpec(
        id="downstream_missing",
        translation_key="downstream_configuration",
        summary="The configured downstream NIC is not present",
        exact=("Configured downstream NIC is not present",),
    ),
    FaultSpec(
        id="downstream_missing",
        translation_key="downstream_configuration",
        summary="A USB Ethernet downstream adapter is not present",
        exact=("USB Ethernet downstream is not present",),
    ),
    FaultSpec(
        id="downstream_ambiguous",
        translation_key="downstream_configuration",
        summary="More than one eligible USB Ethernet adapter is attached",
        exact=("Multiple USB Ethernet adapters detected; set downstream_mac",),
    ),
    FaultSpec(
        id="downstream_interface_overlap",
        translation_key="downstream_configuration",
        summary="The downstream NIC must differ from the management and upstream interfaces",
        exact=("Downstream NIC must differ from management and upstream interfaces",),
    ),
    FaultSpec(
        id="downstream_host_managed",
        translation_key="downstream_configuration",
        summary="The downstream adapter has host-managed IPv4 configuration",
        exact=("Downstream interface has host-managed IPv4 addresses",),
    ),
    FaultSpec(
        id="downstream_inactive",
        translation_key="downstream_configuration",
        summary="The app-owned downstream address is unavailable",
        exact=("App-owned downstream address is unavailable",),
    ),
    FaultSpec(
        id="downstream_address_conflict",
        translation_key="downstream_configuration",
        summary="The downstream adapter has unexpected IPv4 addresses",
        exact=("Downstream interface has unexpected IPv4 addresses",),
    ),
    FaultSpec(
        id="downstream_unavailable",
        translation_key="downstream_configuration",
        summary="The downstream interface is unavailable",
        exact=("Downstream interface is unavailable",),
    ),
    FaultSpec(
        id="downstream_ipv6_active",
        translation_key="downstream_configuration",
        summary="IPv6 is active on the downstream NIC",
        exact=("IPv6 is active on downstream NIC",),
    ),
    FaultSpec(
        id="downstream_ipv6_unverified",
        translation_key="downstream_configuration",
        summary="The gateway could not verify downstream IPv6 state",
        exact=("Cannot verify downstream IPv6 state",),
    ),
    FaultSpec(
        id="upstream_ipv6_active",
        translation_key="host_configuration",
        summary="IPv6 is active on the mobile upstream",
        exact=("IPv6 is active on mobile upstream",),
    ),
    FaultSpec(
        id="upstream_ipv6_unverified",
        translation_key="host_configuration",
        summary="The gateway could not verify mobile upstream IPv6 state",
        exact=("Cannot verify upstream IPv6 state",),
    ),
    FaultSpec(
        id="policy_ownership_unavailable",
        translation_key="policy_configuration",
        summary="The gateway could not inspect policy-routing ownership",
        exact=("Cannot inspect policy-routing ownership",),
    ),
)
