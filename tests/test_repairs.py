from __future__ import annotations

from homeassistant.helpers.issue_registry import async_get

from custom_components.ha_cellular_gateway.const import DOMAIN
from custom_components.ha_cellular_gateway.repairs import (
    active_repair_keys,
    repair_issue_id,
    sync_repairs,
)


def test_active_repair_keys_empty() -> None:
    assert active_repair_keys({}) == set()


def test_active_repair_keys_stable_repairable() -> None:
    data = {"issues": [{"translation_key": "host_configuration", "repairable": True, "transient": False}]}
    assert active_repair_keys(data) == {"host_configuration"}


def test_active_repair_keys_transient_ignored() -> None:
    data = {"issues": [{"translation_key": "host_configuration", "repairable": True, "transient": True}]}
    assert active_repair_keys(data) == set()


def test_active_repair_keys_not_repairable_ignored() -> None:
    data = {"issues": [{"translation_key": "host_configuration", "repairable": False, "transient": False}]}
    assert active_repair_keys(data) == set()


def test_active_repair_keys_unknown_key_ignored() -> None:
    data = {"issues": [{"translation_key": "unknown_key", "repairable": True, "transient": False}]}
    assert active_repair_keys(data) == set()


def test_active_repair_keys_non_dict_ignored() -> None:
    assert active_repair_keys({"issues": ["not_a_dict"]}) == set()


def test_repair_issue_id() -> None:
    assert repair_issue_id("entry_abc", "host_configuration") == "entry_abc_host_configuration"


async def test_sync_repairs_creates_issue(hass) -> None:
    data = {"issues": [{"translation_key": "host_configuration", "repairable": True, "transient": False}]}
    result = sync_repairs(hass, "entry_1", "My Gateway", set(), data)
    assert result == {"host_configuration"}
    assert (DOMAIN, "entry_1_host_configuration") in async_get(hass).issues


async def test_sync_repairs_deletes_resolved_issue(hass) -> None:
    data = {"issues": [{"translation_key": "host_configuration", "repairable": True, "transient": False}]}
    existing = sync_repairs(hass, "entry_1", "My Gateway", set(), data)
    result = sync_repairs(hass, "entry_1", "My Gateway", existing, {})
    assert result == set()
    assert (DOMAIN, "entry_1_host_configuration") not in async_get(hass).issues


async def test_sync_repairs_idempotent(hass) -> None:
    data = {"issues": [{"translation_key": "host_configuration", "repairable": True, "transient": False}]}
    first = sync_repairs(hass, "entry_1", "My Gateway", set(), data)
    second = sync_repairs(hass, "entry_1", "My Gateway", first, data)
    assert second == {"host_configuration"}
    assert (DOMAIN, "entry_1_host_configuration") in async_get(hass).issues
