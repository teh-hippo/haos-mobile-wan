from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from custom_components.ha_cellular_gateway import async_setup_entry
from custom_components.ha_cellular_gateway.api import GatewayApiAuthError, GatewayApiError
from custom_components.ha_cellular_gateway.const import DOMAIN


@pytest.fixture(autouse=True)
def mock_client_session():
    with patch(
        "custom_components.ha_cellular_gateway.async_get_clientsession",
        return_value=object(),
    ):
        yield


async def test_setup_entry_and_unload(
    hass,
    mock_config_entry,
    status_payload: dict[str, object],
) -> None:
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.ha_cellular_gateway.api.GatewayApi.status",
        AsyncMock(return_value=status_payload),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data.data == status_payload
    assert hass.states.get("switch.haos_mobile_wan_enabled").state == "on"
    assert (
        hass.states.get("sensor.haos_mobile_wan_active_connection").state
        == "iphone_usb"
    )
    assert hass.states.get("binary_sensor.haos_mobile_wan_safety_checks").state == "on"

    registry = er.async_get(hass)
    unique_ids = {entry.unique_id for entry in registry.entities.values()}
    assert f"{mock_config_entry.entry_id}_mobile_connection" in unique_ids
    assert f"{mock_config_entry.entry_id}_active_connection" in unique_ids
    assert f"{mock_config_entry.entry_id}_enabled" in unique_ids
    assert f"{mock_config_entry.entry_id}_safety_checks" in unique_ids
    assert f"{mock_config_entry.entry_id}_reconcile" in unique_ids

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_entry_marks_entry_for_retry(hass, mock_config_entry) -> None:
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.ha_cellular_gateway.api.GatewayApi.status",
        AsyncMock(side_effect=GatewayApiError("offline")),
    ):
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_async_setup_entry_raises_not_ready(hass, mock_config_entry) -> None:
    with (
        patch(
            "custom_components.ha_cellular_gateway.async_get_clientsession",
            return_value=object(),
        ),
        patch(
            "custom_components.ha_cellular_gateway.GatewayCoordinator.async_config_entry_first_refresh",
            AsyncMock(side_effect=ConfigEntryNotReady("offline")),
        ),
    ):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, mock_config_entry)


async def test_reload_entry(hass, mock_config_entry, status_payload: dict[str, object]) -> None:
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.ha_cellular_gateway.api.GatewayApi.status",
        AsyncMock(return_value=status_payload),
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert DOMAIN in hass.config.components


async def test_setup_entry_triggers_reauth_on_auth_failure(hass, mock_config_entry) -> None:
    mock_config_entry.add_to_hass(hass)

    with patch(
        "custom_components.ha_cellular_gateway.api.GatewayApi.status",
        AsyncMock(side_effect=GatewayApiAuthError("bad token")),
    ):
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
