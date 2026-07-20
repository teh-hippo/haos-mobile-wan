from __future__ import annotations

HOST_ERRORS: dict[str, tuple[str, str | None, str]] = {
    "Persistent ownership state is invalid": (
        "persistent_ownership_state_invalid",
        "state_invalid",
        "Saved gateway ownership state is invalid",
    ),
    "Management interface/address baseline does not match": (
        "management_baseline_mismatch",
        "host_configuration",
        "The management baseline no longer matches the configured host state",
    ),
    "Management interface is unavailable": (
        "management_interface_unavailable",
        "host_configuration",
        "The management interface is unavailable",
    ),
    "Host IPv4 forwarding is not enabled": (
        "ipv4_forwarding_disabled",
        "host_configuration",
        "Host IPv4 forwarding is disabled",
    ),
    "Cannot verify host IPv4 forwarding": (
        "ipv4_forwarding_unverified",
        "host_configuration",
        "The gateway could not verify host IPv4 forwarding",
    ),
    "iptables is not using the nf_tables backend": (
        "iptables_backend_mismatch",
        "host_configuration",
        "iptables is not using the nf_tables backend",
    ),
    "Docker DOCKER-USER chain is missing": (
        "docker_user_missing",
        "host_configuration",
        "The Docker DOCKER-USER chain is missing",
    ),
    "Cannot inspect the host firewall backend": (
        "firewall_backend_unavailable",
        "host_configuration",
        "The gateway could not inspect the host firewall backend",
    ),
    "Upstream interface is unavailable": (
        "upstream_interface_unavailable",
        None,
        "The upstream interface is unavailable",
    ),
    "Upstream interface/address is not active": (
        "upstream_interface_inactive",
        None,
        "The upstream interface is not active",
    ),
    "Hotspot Wi-Fi adapter is disabled": (
        "hotspot_adapter_disabled",
        "hotspot_adapter_disabled",
        "The hotspot Wi-Fi adapter is disabled",
    ),
    "Hotspot Wi-Fi is enabled but not associated": (
        "hotspot_not_associated",
        "hotspot_not_associated",
        "The hotspot Wi-Fi adapter is enabled but has not associated with the phone",
    ),
    "Management interface is not the main default route": (
        "management_default_route_missing",
        "host_configuration",
        "The management interface is not the main default route",
    ),
    "Mobile upstream has a main-table default route": (
        "upstream_default_route_present",
        "host_configuration",
        "The mobile upstream still has a main default route",
    ),
    "Cannot inspect main-table default routes": (
        "default_routes_unavailable",
        "host_configuration",
        "The gateway could not inspect the main default routes",
    ),
    "Configured downstream NIC is not present": (
        "downstream_missing",
        "downstream_configuration",
        "The configured downstream NIC is not present",
    ),
    "USB Ethernet downstream is not present": (
        "downstream_missing",
        "downstream_configuration",
        "A USB Ethernet downstream adapter is not present",
    ),
    "Multiple USB Ethernet adapters detected; set downstream_mac": (
        "downstream_ambiguous",
        "downstream_configuration",
        "More than one eligible USB Ethernet adapter is attached",
    ),
    "Downstream NIC must differ from management and upstream interfaces": (
        "downstream_interface_overlap",
        "downstream_configuration",
        "The downstream NIC must differ from the management and upstream interfaces",
    ),
    "Downstream interface has host-managed IPv4 addresses": (
        "downstream_host_managed",
        "downstream_configuration",
        "The downstream adapter has host-managed IPv4 configuration",
    ),
    "App-owned downstream address is unavailable": (
        "downstream_inactive",
        "downstream_configuration",
        "The app-owned downstream address is unavailable",
    ),
    "Downstream interface has unexpected IPv4 addresses": (
        "downstream_address_conflict",
        "downstream_configuration",
        "The downstream adapter has unexpected IPv4 addresses",
    ),
    "Downstream interface is unavailable": (
        "downstream_unavailable",
        "downstream_configuration",
        "The downstream interface is unavailable",
    ),
    "IPv6 is active on downstream NIC": (
        "downstream_ipv6_active",
        "downstream_configuration",
        "IPv6 is active on the downstream NIC",
    ),
    "Cannot verify downstream IPv6 state": (
        "downstream_ipv6_unverified",
        "downstream_configuration",
        "The gateway could not verify downstream IPv6 state",
    ),
    "IPv6 is active on mobile upstream": (
        "upstream_ipv6_active",
        "host_configuration",
        "IPv6 is active on the mobile upstream",
    ),
    "Cannot verify upstream IPv6 state": (
        "upstream_ipv6_unverified",
        "host_configuration",
        "The gateway could not verify mobile upstream IPv6 state",
    ),
    "Cannot inspect policy-routing ownership": (
        "policy_ownership_unavailable",
        "policy_configuration",
        "The gateway could not inspect policy-routing ownership",
    ),
}
