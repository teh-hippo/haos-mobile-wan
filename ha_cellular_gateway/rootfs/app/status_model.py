from __future__ import annotations

from typing import Any

WAITING_ISSUE_IDS = {
    "hotspot_not_associated",
    "upstream_interface_inactive",
    "upstream_interface_unavailable",
    "upstream_not_ready",
    "upstream_waiting_for_device",
}


def derive_gateway_state(
    enabled: bool,
    applied: bool,
    issues: list[dict[str, Any]],
) -> str:
    if not enabled:
        return "disabled"
    if actionable_messages(issues):
        return "error"
    if applied:
        return "connected"
    if any(str(issue["id"]) in WAITING_ISSUE_IDS for issue in issues):
        return "waiting"
    return "connecting"


def derive_health(issues: list[dict[str, Any]]) -> tuple[str, list[str]]:
    messages = actionable_messages(issues)
    return ("attention" if messages else "healthy", messages)


def actionable_messages(issues: list[dict[str, Any]]) -> list[str]:
    return list(
        dict.fromkeys(
            str(issue["message"])
            for issue in issues
            if not issue["transient"]
        )
    )
