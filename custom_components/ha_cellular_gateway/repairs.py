from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)

from .const import DOMAIN
from .models import GatewayIssue

_VALID_TRANSLATION_KEYS = {
    "state_invalid",
    "host_configuration",
    "downstream_configuration",
    "policy_configuration",
    "upstream_configuration",
}


def active_repair_keys(issues: list[GatewayIssue]) -> set[str]:
    keys: set[str] = set()
    for issue in issues:
        if not issue["repairable"] or issue["transient"]:
            continue
        key = issue["translation_key"]
        if isinstance(key, str) and key in _VALID_TRANSLATION_KEYS:
            keys.add(key)
    return keys


def repair_issue_id(entry_id: str, translation_key: str) -> str:
    return f"{entry_id}_{translation_key}"


def sync_repairs(
    hass: HomeAssistant,
    entry_id: str,
    entry_title: str,
    current_repairs: set[str],
    issues: list[GatewayIssue],
) -> set[str]:
    desired = active_repair_keys(issues)
    for translation_key in current_repairs - desired:
        async_delete_issue(hass, DOMAIN, repair_issue_id(entry_id, translation_key))
    for translation_key in desired - current_repairs:
        async_create_issue(
            hass,
            DOMAIN,
            repair_issue_id(entry_id, translation_key),
            is_fixable=False,
            issue_domain=DOMAIN,
            severity=IssueSeverity.ERROR,
            translation_key=translation_key,
            translation_placeholders={"entry_title": entry_title},
        )
    return desired
