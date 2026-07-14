from __future__ import annotations

from homeassistant.helpers.issue_registry import async_get

from custom_components.ha_cellular_gateway.const import DOMAIN
from custom_components.ha_cellular_gateway.repairs import (
    active_repair_keys,
    repair_issue_id,
    sync_repairs,
)


def test_active_repair_keys_empty() -> None:
    assert active_repair_keys([]) == set()


def test_active_repair_keys_stable_repairable() -> None:
    issues = [{"id": "x", "translation_key": "host_configuration", "repairable": True, "transient": False, "message": "m"}]
    assert active_repair_keys(issues) == {"host_configuration"}  # type: ignore[arg-type]


def test_active_repair_keys_transient_ignored() -> None:
    issues = [{"id": "x", "translation_key": "host_configuration", "repairable": True, "transient": True, "message": "m"}]
    assert active_repair_keys(issues) == set()  # type: ignore[arg-type]


def test_active_repair_keys_not_repairable_ignored() -> None:
    issues = [{"id": "x", "translation_key": "host_configuration", "repairable": False, "transient": False, "message": "m"}]
    assert active_repair_keys(issues) == set()  # type: ignore[arg-type]


def test_active_repair_keys_unknown_key_ignored() -> None:
    issues = [{"id": "x", "translation_key": "unknown_key", "repairable": True, "transient": False, "message": "m"}]
    assert active_repair_keys(issues) == set()  # type: ignore[arg-type]


def test_repair_issue_id() -> None:
    assert repair_issue_id("entry_abc", "host_configuration") == "entry_abc_host_configuration"


async def test_sync_repairs_creates_issue(hass) -> None:
    issues = [{"id": "x", "translation_key": "host_configuration", "repairable": True, "transient": False, "message": "m"}]
    result = sync_repairs(hass, "entry_1", "My Gateway", set(), issues)  # type: ignore[arg-type]
    assert result == {"host_configuration"}
    assert (DOMAIN, "entry_1_host_configuration") in async_get(hass).issues


async def test_sync_repairs_deletes_resolved_issue(hass) -> None:
    issues = [{"id": "x", "translation_key": "host_configuration", "repairable": True, "transient": False, "message": "m"}]
    existing = sync_repairs(hass, "entry_1", "My Gateway", set(), issues)  # type: ignore[arg-type]
    result = sync_repairs(hass, "entry_1", "My Gateway", existing, [])
    assert result == set()
    assert (DOMAIN, "entry_1_host_configuration") not in async_get(hass).issues


async def test_sync_repairs_idempotent(hass) -> None:
    issues = [{"id": "x", "translation_key": "host_configuration", "repairable": True, "transient": False, "message": "m"}]
    first = sync_repairs(hass, "entry_1", "My Gateway", set(), issues)  # type: ignore[arg-type]
    second = sync_repairs(hass, "entry_1", "My Gateway", first, issues)  # type: ignore[arg-type]
    assert second == {"host_configuration"}
    assert (DOMAIN, "entry_1_host_configuration") in async_get(hass).issues


async def test_sync_repairs_clears_on_unload(hass) -> None:
    issues = [{"id": "x", "translation_key": "downstream_configuration", "repairable": True, "transient": False, "message": "m"}]
    existing = sync_repairs(hass, "entry_1", "My Gateway", set(), issues)  # type: ignore[arg-type]
    assert (DOMAIN, "entry_1_downstream_configuration") in async_get(hass).issues

    result = sync_repairs(hass, "entry_1", "My Gateway", existing, [])
    assert result == set()
    assert (DOMAIN, "entry_1_downstream_configuration") not in async_get(hass).issues


async def test_sync_repairs_transient_not_created(hass) -> None:
    issues = [{"id": "upstream_waiting_for_device", "translation_key": None, "repairable": False, "transient": True, "message": "Waiting"}]
    result = sync_repairs(hass, "entry_1", "My Gateway", set(), issues)  # type: ignore[arg-type]
    assert result == set()
    assert not async_get(hass).issues
