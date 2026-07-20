from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .status_issue_host import HOST_ERRORS
from .status_issue_upstream import (
    TRANSIENT_EXACT,
    UPSTREAM_ERRORS,
    UPSTREAM_STABLE_STATES,
    UPSTREAM_TRANSIENT_STATES,
)

EXACT_ERRORS = {**HOST_ERRORS, **UPSTREAM_ERRORS}


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
        warning_issue = _issue_from_error(warning)
        if warning_issue is None:
            continue
        warning_issue["blocking"] = False
        issue_id = str(warning_issue["id"])
        if issue_id in seen:
            continue
        seen.add(issue_id)
        issues.append(warning_issue)

    if last_error and not safety_error_list:
        issue = _issue_from_error(last_error) or _generic_issue(last_error)
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
        return _issue(
            "upstream_driver_inactive",
            "upstream_configuration",
            "The host iPhone USB network driver is not active",
        )
    if pairing_state in UPSTREAM_STABLE_STATES:
        issue_id, message = UPSTREAM_STABLE_STATES[pairing_state]
        return _issue(issue_id, "upstream_configuration", message)
    if pairing_state in UPSTREAM_TRANSIENT_STATES:
        issue_id, message = UPSTREAM_TRANSIENT_STATES[pairing_state]
        return _issue(issue_id, None, message, transient=True)
    return None


def _issue_from_error(error: str) -> dict[str, Any] | None:
    if error in EXACT_ERRORS:
        issue_id, key, message = EXACT_ERRORS[error]
        return _issue(issue_id, key, message, transient=error in TRANSIENT_EXACT)
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
    if error.startswith("Required command is unavailable: "):
        return _issue(
            "upstream_required_command_unavailable",
            "upstream_configuration",
            "A required iPhone USB command is not installed",
        )
    if error.startswith("Invalid app configuration: Hotspot "):
        return _issue(
            "hotspot_configuration_failed",
            "hotspot_configuration",
            "The hotspot Wi-Fi profile could not be configured",
        )
    if error.startswith(
        (
            "Cannot read app configuration:",
            "Invalid app configuration:",
        )
    ):
        return _issue(
            "app_configuration_unavailable",
            "host_configuration",
            "The app could not load a safe host configuration",
        )
    if error.startswith("Hotspot Wi-Fi provisioning failed:"):
        return _issue(
            "hotspot_configuration_failed",
            "hotspot_configuration",
            "The hotspot Wi-Fi profile could not be configured",
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
    if error.startswith("Auto-disable cleanup failed:"):
        return _issue("auto_disable_cleanup_failed", None, error)
    if error.startswith("Auto-stop request failed:"):
        return _issue("auto_stop_request_failed", None, error)
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
        "blocking": True,
        "message": message,
    }
