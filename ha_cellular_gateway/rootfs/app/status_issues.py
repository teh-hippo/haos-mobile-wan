from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .status_issue_host import HOST_ERRORS
from .status_issue_rules import issue_from_rules
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
    rule_match = issue_from_rules(error)
    if rule_match is not None:
        issue_id, key, message = rule_match
        return _issue(issue_id, key, message)
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
