from __future__ import annotations

from collections.abc import Iterable
from typing import Any

_UPSTREAM_TRANSIENT_STATES = {
    "waiting_for_device": ("upstream_waiting_for_device", "Waiting for an iPhone USB upstream"),
    "waiting_for_hotspot": ("upstream_waiting_for_hotspot", "Waiting for iPhone Personal Hotspot"),
    "waiting_for_profile": ("upstream_waiting_for_profile", "Waiting for the NetworkManager iPhone USB profile"),
    "waiting_for_interface": ("upstream_waiting_for_interface", "Waiting for the iPhone USB network interface"),
    "not_ready": ("upstream_not_ready", "Upstream connectivity is not ready"),
    "waiting_for_trust": ("upstream_waiting_for_trust", "Waiting for iPhone USB trust confirmation"),
    "waiting_for_unlock": ("upstream_waiting_for_unlock", "Waiting for iPhone to be unlocked"),
}

_UPSTREAM_STABLE_STATES: dict[str, tuple[str, str]] = {
    "daemon_failed": ("upstream_daemon_failed", "The iPhone USB pairing helper failed to start"),
    "profile_failed": ("upstream_profile_failed", "The NetworkManager iPhone USB profile could not be configured"),
    "profile_conflict": ("upstream_profile_conflict", "A different NetworkManager profile controls the iPhone USB interface"),
    "invalid_lease": ("upstream_invalid_lease", "The iPhone USB NetworkManager lease is invalid"),
    "multiple_devices": ("upstream_multiple_devices", "Multiple iPhone USB upstream devices detected"),
    "pairing_failed": ("upstream_pairing_failed", "iPhone USB pairing failed"),
}

_EXACT_ERRORS: dict[str, tuple[str, str | None, str]] = {
    "Persistent ownership state is invalid": ("persistent_ownership_state_invalid", "state_invalid", "Saved gateway ownership state is invalid"),
    "Management interface/address baseline does not match": ("management_baseline_mismatch", "host_configuration", "The management baseline no longer matches the configured host state"),
    "Management interface is unavailable": ("management_interface_unavailable", "host_configuration", "The management interface is unavailable"),
    "Host IPv4 forwarding is not enabled": ("ipv4_forwarding_disabled", "host_configuration", "Host IPv4 forwarding is disabled"),
    "Cannot verify host IPv4 forwarding": ("ipv4_forwarding_unverified", "host_configuration", "The gateway could not verify host IPv4 forwarding"),
    "iptables is not using the nf_tables backend": ("iptables_backend_mismatch", "host_configuration", "iptables is not using the nf_tables backend"),
    "Docker DOCKER-USER chain is missing": ("docker_user_missing", "host_configuration", "The Docker DOCKER-USER chain is missing"),
    "Cannot inspect the host firewall backend": ("firewall_backend_unavailable", "host_configuration", "The gateway could not inspect the host firewall backend"),
    "Upstream interface is unavailable": ("upstream_interface_unavailable", None, "The upstream interface is unavailable"),
    "Upstream interface/address is not active": ("upstream_interface_inactive", None, "The upstream interface is not active"),
    "Hotspot Wi-Fi adapter is disabled": ("hotspot_adapter_disabled", "hotspot_adapter_disabled", "The hotspot Wi-Fi adapter is disabled"),
    "Hotspot Wi-Fi is enabled but not associated": ("hotspot_not_associated", "hotspot_not_associated", "The hotspot Wi-Fi adapter is enabled but has not associated with the phone"),
    "Management interface is not the main default route": ("management_default_route_missing", "host_configuration", "The management interface is not the main default route"),
    "Mobile upstream has a main-table default route": ("upstream_default_route_present", "host_configuration", "The mobile upstream still has a main default route"),
    "Cannot inspect main-table default routes": ("default_routes_unavailable", "host_configuration", "The gateway could not inspect the main default routes"),
    "Configured downstream NIC is not present": ("downstream_missing", "downstream_configuration", "The configured downstream NIC is not present"),
    "USB Ethernet downstream is not present": ("downstream_missing", "downstream_configuration", "A USB Ethernet downstream adapter is not present"),
    "Multiple USB Ethernet adapters detected; set downstream_mac": ("downstream_ambiguous", "downstream_configuration", "More than one eligible USB Ethernet adapter is attached"),
    "Downstream NIC must differ from management and upstream interfaces": ("downstream_interface_overlap", "downstream_configuration", "The downstream NIC must differ from the management and upstream interfaces"),
    "Downstream interface has host-managed IPv4 addresses": ("downstream_host_managed", "downstream_configuration", "The downstream adapter has host-managed IPv4 configuration"),
    "App-owned downstream address is unavailable": ("downstream_inactive", "downstream_configuration", "The app-owned downstream address is unavailable"),
    "Downstream interface has unexpected IPv4 addresses": ("downstream_address_conflict", "downstream_configuration", "The downstream adapter has unexpected IPv4 addresses"),
    "Downstream interface is unavailable": ("downstream_unavailable", "downstream_configuration", "The downstream interface is unavailable"),
    "IPv6 is active on downstream NIC": ("downstream_ipv6_active", "downstream_configuration", "IPv6 is active on the downstream NIC"),
    "Cannot verify downstream IPv6 state": ("downstream_ipv6_unverified", "downstream_configuration", "The gateway could not verify downstream IPv6 state"),
    "IPv6 is active on mobile upstream": ("upstream_ipv6_active", "host_configuration", "IPv6 is active on the mobile upstream"),
    "Cannot verify upstream IPv6 state": ("upstream_ipv6_unverified", "host_configuration", "The gateway could not verify mobile upstream IPv6 state"),
    "Cannot inspect policy-routing ownership": ("policy_ownership_unavailable", "policy_configuration", "The gateway could not inspect policy-routing ownership"),
    "USB device access is unavailable; enable the app usb permission": ("upstream_usb_access_unavailable", "upstream_configuration", "USB device access is unavailable; enable the app USB permission"),
    "Wi-Fi upstream is the management interface": ("wifi_management_overlap", "hotspot_configuration", "The Wi-Fi upstream is the management interface"),
    "The dedicated Wi-Fi adapter is the management interface": ("wifi_custody_management", "hotspot_configuration", "The dedicated Wi-Fi adapter is the management interface"),
    "The dedicated Wi-Fi adapter is not present": ("wifi_device_missing", "hotspot_configuration", "The dedicated Wi-Fi adapter is not present"),
    "NetworkManager does not manage the dedicated Wi-Fi adapter": ("wifi_device_unmanaged", "hotspot_configuration", "NetworkManager does not manage the dedicated Wi-Fi adapter"),
    "The Wi-Fi radio is turned off": ("wifi_radio_off", "hotspot_configuration", "The Wi-Fi radio is turned off"),
    "The Wi-Fi radio is hardware-blocked": ("wifi_radio_blocked", "hotspot_configuration", "The Wi-Fi radio is hardware-blocked"),
    "A foreign Wi-Fi connection still controls the dedicated adapter": ("wifi_displace_failed", "hotspot_configuration", "A foreign Wi-Fi connection still controls the dedicated adapter"),
    "A legacy Supervisor Wi-Fi profile could not be removed": ("lineage_wifi_delete_failed", "hotspot_configuration", "A legacy Supervisor Wi-Fi profile could not be removed"),
    "The hotspot rejected the configured Wi-Fi password": ("hotspot_auth_failed", "hotspot_configuration", "The hotspot rejected the configured Wi-Fi password"),
    "The hotspot network is not currently visible": ("hotspot_target_absent", None, "The hotspot network is not currently visible"),
    "Associating with the hotspot network": ("hotspot_connecting", None, "Associating with the hotspot network"),
    "Wi-Fi adapter runtime restoration is incomplete": ("wifi_restoration_incomplete", "hotspot_configuration", "The dedicated Wi-Fi adapter runtime state was not fully restored"),
    "The marked Wi-Fi adapter runtime restoration is pending": ("wifi_restoration_pending", None, "The dedicated Wi-Fi adapter runtime restoration is pending"),
    "iPhone USB has a foreign NetworkManager profile": ("upstream_foreign_profile", "upstream_configuration", "A foreign NetworkManager profile can control iPhone USB"),
    "The app-owned iPhone USB profile has unexpected settings": ("upstream_profile_drift", "upstream_configuration", "The app-owned iPhone USB profile has unexpected settings"),
    "The app-owned Wi-Fi hotspot profile has unexpected settings": ("wifi_profile_drift", "hotspot_configuration", "The app-owned Wi-Fi hotspot profile has unexpected settings"),
    "Wi-Fi hotspot credentials are not configured": ("hotspot_credentials_missing", "hotspot_configuration", "Wi-Fi hotspot credentials are not configured"),
    "NetworkManager Wi-Fi inspection is unavailable": ("wifi_inspection_waiting", None, "Waiting for NetworkManager Wi-Fi inspection"),
}

_TRANSIENT_EXACT = {
    "Hotspot Wi-Fi is enabled but not associated",
    "Upstream interface is unavailable",
    "Upstream interface/address is not active",
    "The hotspot network is not currently visible",
    "Associating with the hotspot network",
    "The marked Wi-Fi adapter runtime restoration is pending",
    "NetworkManager Wi-Fi inspection is unavailable",
}


def build_status_issues(
    safety_errors: Iterable[str],
    last_error: str | None,
    upstream_status: dict[str, Any],
    connection_warnings: Iterable[str] = (),
    runtime_errors: Iterable[str] = (),
) -> list[dict[str, Any]]:
    safety_error_list = list(safety_errors)
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()
    suppressed_errors: set[str] = set()

    upstream_issue = _issue_from_upstream(upstream_status)
    if upstream_issue is not None:
        issues.append(upstream_issue)
        seen.add(str(upstream_issue["id"]))
        pairing_message = upstream_status.get("upstream_pairing_message")
        if isinstance(pairing_message, str) and pairing_message:
            suppressed_errors.add(pairing_message)

    for error in safety_error_list:
        if error == "Safety checks have not run yet" or error in suppressed_errors:
            continue
        issue = _issue_from_error(error) or _generic_issue(error)
        issue_id = str(issue["id"])
        if issue_id in seen:
            continue
        seen.add(issue_id)
        issues.append(issue)

    for warning in connection_warnings:
        issue = _issue_from_error(warning)
        if issue is None:
            continue
        issue_id = str(issue["id"])
        if issue_id in seen:
            continue
        seen.add(issue_id)
        issues.append(issue)

    if last_error and not safety_error_list:
        issue = _issue_from_error(last_error) or _generic_issue(last_error)
        if issue is not None:
            issue_id = str(issue["id"])
            if issue_id not in seen:
                seen.add(issue_id)
                issues.append(issue)

    for error in runtime_errors:
        issue = _issue_from_error(error) or _generic_issue(error)
        issue_id = str(issue["id"])
        if issue_id not in seen:
            seen.add(issue_id)
            issues.append(issue)

    return issues


def _issue_from_upstream(upstream_status: dict[str, Any]) -> dict[str, Any] | None:
    pairing_state = upstream_status.get("upstream_pairing_state")
    if not isinstance(pairing_state, str):
        return None
    pairing_message = upstream_status.get("upstream_pairing_message")
    if (
        isinstance(pairing_message, str)
        and "ipheth driver is not active" in pairing_message
    ):
        return _issue("upstream_driver_inactive", "upstream_configuration", "The host iPhone USB network driver is not active")
    if pairing_state in _UPSTREAM_STABLE_STATES:
        issue_id, message = _UPSTREAM_STABLE_STATES[pairing_state]
        return _issue(issue_id, "upstream_configuration", message)
    if pairing_state in _UPSTREAM_TRANSIENT_STATES:
        issue_id, message = _UPSTREAM_TRANSIENT_STATES[pairing_state]
        return _issue(issue_id, None, message, transient=True)
    return None


def _issue_from_error(error: str) -> dict[str, Any] | None:
    if error in _EXACT_ERRORS:
        issue_id, key, message = _EXACT_ERRORS[error]
        return _issue(issue_id, key, message, transient=error in _TRANSIENT_EXACT)
    if error.startswith("Strict rp_filter is enabled on "):
        return _issue("strict_rp_filter_enabled", "host_configuration", "Strict rp_filter is enabled on a required interface")
    if error.startswith("Cannot read rp_filter for "):
        return _issue("rp_filter_unavailable", "host_configuration", "The gateway could not read rp_filter on a required interface")
    if error.startswith("Unexpected main-table default route:"):
        return _issue("unexpected_default_route", "host_configuration", "An unexpected main default route is present")
    if error.startswith("Policy priority "):
        return _issue("policy_priority_conflict", "policy_configuration", "A required policy-routing priority is already in use")
    if "already has a foreign policy rule" in error:
        return _issue("policy_foreign_rule", "policy_configuration", "A foreign policy rule is using the gateway routing table")
    if "contains an unexpected route" in error:
        return _issue("policy_unexpected_route", "policy_configuration", "The gateway routing table contains an unexpected route")
    if error.startswith("Required command is unavailable: "):
        return _issue("upstream_required_command_unavailable", "upstream_configuration", "A required iPhone USB command is not installed")
    if error.startswith("Invalid app configuration: Hotspot "):
        return _issue("hotspot_configuration_failed", "hotspot_configuration", "The hotspot Wi-Fi profile could not be configured")
    if error.startswith(
        (
            "Cannot read app configuration:",
            "Invalid app configuration:",
        )
    ):
        return _issue("app_configuration_unavailable", "host_configuration", "The app could not load a safe host configuration")
    if error.startswith("Hotspot Wi-Fi provisioning failed:"):
        return _issue("hotspot_configuration_failed", "hotspot_configuration", "The hotspot Wi-Fi profile could not be configured")
    if error.startswith("Safety inspection failed:"):
        return _issue("safety_inspection_failed", "host_configuration", "The gateway could not complete its safety inspection")
    if error.startswith("Activation failed:"):
        return _issue("activation_failed", "host_configuration", "The gateway could not apply the requested network state")
    if error.startswith("Auto-disable option update failed:"):
        return _issue("auto_disable_update_failed", None, error)
    if error.startswith("Auto-disable cleanup failed:"):
        return _issue("auto_disable_cleanup_failed", None, error)
    if error.startswith("Auto-disable state persistence failed:"):
        return _issue("auto_disable_state_failed", None, error)
    if error.startswith("Hotspot Wi-Fi deactivation failed:"):
        return _issue("hotspot_deactivation_failed", None, error)
    if error.startswith("NetworkManager profile operation failed:"):
        return _issue("networkmanager_profile_failed", None, error)
    if error.startswith("NetworkManager profile cleanup failed:"):
        return _issue("networkmanager_cleanup_failed", None, error)
    if error.startswith("NetworkManager ownership journal failed:"):
        return _issue("networkmanager_journal_failed", None, error)
    if error.startswith("Management interface changed from "):
        return _issue(
            "management_interface_changed",
            "host_configuration",
            error,
        )
    if error == "Hotspot Wi-Fi interface is the management interface":
        return _issue("hotspot_management_overlap", None, error)
    return None


def _generic_issue(error: str) -> dict[str, Any]:
    return _issue("gateway_runtime_error", None, error)


def _issue(
    issue_id: str,
    translation_key: str | None,
    message: str,
    *,
    transient: bool = False,
) -> dict[str, Any]:
    return {
        "id": issue_id,
        "translation_key": translation_key,
        "repairable": bool(translation_key) and not transient,
        "transient": transient,
        "message": message,
    }
