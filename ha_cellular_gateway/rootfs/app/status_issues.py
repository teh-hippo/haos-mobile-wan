from __future__ import annotations

from collections.abc import Iterable
from typing import Any

_UPSTREAM_TRANSIENT_STATES = {
    "waiting_for_device": ("upstream_waiting_for_device", "Waiting for an iPhone USB upstream"),
    "waiting_for_dhcp": ("upstream_waiting_for_dhcp", "Waiting for the iPhone USB upstream DHCP lease"),
    "multiple_devices": ("upstream_multiple_devices", "Multiple iPhone USB upstream devices detected"),
    "waiting_for_interface": ("upstream_waiting_for_interface", "Waiting for the iPhone USB network interface"),
    "not_ready": ("upstream_not_ready", "Upstream connectivity is not ready"),
}


def build_status_issues(
    safety_errors: Iterable[str],
    last_error: str | None,
    upstream_status: dict[str, Any],
) -> list[dict[str, Any]]:
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

    for error in safety_errors:
        if error == "Safety checks have not run yet" or error in suppressed_errors:
            continue
        issue = _issue_from_error(error)
        if issue is None:
            continue
        issue_id = str(issue["id"])
        if issue_id in seen:
            continue
        seen.add(issue_id)
        issues.append(issue)

    if last_error and not any(last_error == error for error in safety_errors):
        issue = _issue_from_error(last_error)
        if issue is not None:
            issue_id = str(issue["id"])
            if issue_id not in seen:
                issues.append(issue)

    return issues


def _issue_from_upstream(upstream_status: dict[str, Any]) -> dict[str, Any] | None:
    pairing_state = upstream_status.get("upstream_pairing_state")
    if not isinstance(pairing_state, str):
        return None
    pairing_message = upstream_status.get("upstream_pairing_message")
    driver_inactive = (
        isinstance(pairing_message, str)
        and "ipheth driver is not active" in pairing_message
    )
    if pairing_state == "dry_run_blocked":
        return _issue(
            "upstream_dry_run_blocked",
            "upstream_configuration",
            "Disable dry run before commissioning an iPhone USB upstream",
        )
    if pairing_state == "daemon_failed":
        return _issue(
            "upstream_daemon_failed",
            "upstream_configuration",
            "The iPhone USB pairing helper failed to start",
        )
    if pairing_state == "ownership_conflict":
        return _issue(
            "upstream_ownership_conflict",
            "upstream_configuration",
            "The iPhone USB upstream is already managed by the host",
        )
    if pairing_state == "invalid_lease":
        return _issue(
            "upstream_invalid_lease",
            "upstream_configuration",
            "The iPhone USB upstream lease is invalid",
        )
    if driver_inactive:
        return _issue(
            "upstream_driver_inactive",
            "upstream_configuration",
            "The host iPhone USB network driver is not active",
        )
    if pairing_state in _UPSTREAM_TRANSIENT_STATES:
        issue_id, message = _UPSTREAM_TRANSIENT_STATES[pairing_state]
        return _issue(issue_id, None, message, transient=True)
    return None


def _issue_from_error(error: str) -> dict[str, Any] | None:
    exact: dict[str, dict[str, Any]] = {
        "Persistent ownership state is invalid": _issue(
            "persistent_ownership_state_invalid",
            "state_invalid",
            "Saved gateway ownership state is invalid",
        ),
        "Persistent trial state is invalid": _issue(
            "persistent_trial_state_invalid",
            "state_invalid",
            "Saved gateway trial state is invalid",
        ),
        "Management interface/address baseline does not match": _issue(
            "management_baseline_mismatch",
            "host_configuration",
            "The management baseline no longer matches the configured host state",
        ),
        "Management interface is unavailable": _issue(
            "management_interface_unavailable",
            "host_configuration",
            "The management interface is unavailable",
        ),
        "Host IPv4 forwarding is not enabled": _issue(
            "ipv4_forwarding_disabled",
            "host_configuration",
            "Host IPv4 forwarding is disabled",
        ),
        "Cannot verify host IPv4 forwarding": _issue(
            "ipv4_forwarding_unverified",
            "host_configuration",
            "The gateway could not verify host IPv4 forwarding",
        ),
        "iptables is not using the nf_tables backend": _issue(
            "iptables_backend_mismatch",
            "host_configuration",
            "iptables is not using the nf_tables backend",
        ),
        "Docker DOCKER-USER chain is missing": _issue(
            "docker_user_missing",
            "host_configuration",
            "The Docker DOCKER-USER chain is missing",
        ),
        "Cannot inspect the host firewall backend": _issue(
            "firewall_backend_unavailable",
            "host_configuration",
            "The gateway could not inspect the host firewall backend",
        ),
        "Upstream interface is unavailable": _issue(
            "upstream_interface_unavailable",
            None,
            "The upstream interface is unavailable",
            transient=True,
        ),
        "Upstream interface/address is not active": _issue(
            "upstream_interface_inactive",
            None,
            "The upstream interface is not active",
            transient=True,
        ),
        "Management interface is not the main default route": _issue(
            "management_default_route_missing",
            "host_configuration",
            "The management interface is not the main default route",
        ),
        "Mobile upstream has a main-table default route": _issue(
            "upstream_default_route_present",
            "host_configuration",
            "The mobile upstream still has a main default route",
        ),
        "Cannot inspect main-table default routes": _issue(
            "default_routes_unavailable",
            "host_configuration",
            "The gateway could not inspect the main default routes",
        ),
        "Configured downstream NIC is not present": _issue(
            "downstream_missing",
            "downstream_configuration",
            "The configured downstream NIC is not present",
        ),
        "Downstream NIC must differ from management and upstream interfaces": _issue(
            "downstream_interface_overlap",
            "downstream_configuration",
            "The downstream NIC must differ from the management and upstream interfaces",
        ),
        "Downstream interface/address is not active": _issue(
            "downstream_inactive",
            "downstream_configuration",
            "The downstream interface is not active",
        ),
        "Downstream interface is unavailable": _issue(
            "downstream_unavailable",
            "downstream_configuration",
            "The downstream interface is unavailable",
        ),
        "IPv6 is active on downstream NIC": _issue(
            "downstream_ipv6_active",
            "downstream_configuration",
            "IPv6 is active on the downstream NIC",
        ),
        "Cannot verify downstream IPv6 state": _issue(
            "downstream_ipv6_unverified",
            "downstream_configuration",
            "The gateway could not verify downstream IPv6 state",
        ),
        "IPv6 is active on mobile upstream": _issue(
            "upstream_ipv6_active",
            "host_configuration",
            "IPv6 is active on the mobile upstream",
        ),
        "Cannot verify upstream IPv6 state": _issue(
            "upstream_ipv6_unverified",
            "host_configuration",
            "The gateway could not verify mobile upstream IPv6 state",
        ),
        "Cannot inspect policy-routing ownership": _issue(
            "policy_ownership_unavailable",
            "policy_configuration",
            "The gateway could not inspect policy-routing ownership",
        ),
        "Trial expired and was rolled back": _issue(
            "trial_expired",
            None,
            "The gateway trial expired and was rolled back",
        ),
    }
    if error in exact:
        return exact[error]
    if error.startswith("Strict rp_filter is enabled on "):
        return _issue(
            "strict_rp_filter_enabled",
            "host_configuration",
            "Strict rp_filter is enabled on a required interface",
        )
    if error.startswith("Cannot read rp_filter for "):
        return _issue(
            "rp_filter_unavailable",
            "host_configuration",
            "The gateway could not read rp_filter on a required interface",
        )
    if error.startswith("Unexpected main-table default route:"):
        return _issue(
            "unexpected_default_route",
            "host_configuration",
            "An unexpected main default route is present",
        )
    if error.startswith("Policy priority "):
        return _issue(
            "policy_priority_conflict",
            "policy_configuration",
            "A required policy-routing priority is already in use",
        )
    if "already has a foreign policy rule" in error:
        return _issue(
            "policy_foreign_rule",
            "policy_configuration",
            "A foreign policy rule is using the gateway routing table",
        )
    if "contains an unexpected route" in error:
        return _issue(
            "policy_unexpected_route",
            "policy_configuration",
            "The gateway routing table contains an unexpected route",
        )
    if error.startswith("Safety inspection failed:"):
        return _issue(
            "safety_inspection_failed",
            "host_configuration",
            "The gateway could not complete its safety inspection",
        )
    if error.startswith("Activation failed:"):
        return _issue(
            "activation_failed",
            "host_configuration",
            "The gateway could not apply the requested network state",
        )
    return None


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
