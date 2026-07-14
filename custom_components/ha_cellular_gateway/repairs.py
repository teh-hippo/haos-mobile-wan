from __future__ import annotations

from typing import Any

from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)

from .const import DOMAIN

_VALID_TRANSLATION_KEYS = {
    "state_invalid",
    "host_configuration",
    "downstream_configuration",
    "policy_configuration",
    "upstream_configuration",
}


def active_repair_keys(data: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for issue in data.get("issues", []):
        if not isinstance(issue, dict):
            continue
        if issue.get("repairable") is not True or issue.get("transient") is True:
            continue
        translation_key = issue.get("translation_key")
        if isinstance(translation_key, str) and translation_key in _VALID_TRANSLATION_KEYS:
            keys.add(translation_key)
    return keys


def repair_issue_id(entry_id: str, translation_key: str) -> str:
    return f"{entry_id}_{translation_key}"


def sync_repairs(
    hass,
    entry_id: str,
    entry_title: str,
    current_repairs: set[str],
    data: dict[str, Any],
) -> set[str]:
    desired = active_repair_keys(data)
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
