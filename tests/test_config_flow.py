from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_HASSIO
from homeassistant.const import CONF_URL
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_cellular_gateway.api import GatewayApiError
from custom_components.ha_cellular_gateway.const import CONF_TOKEN, DEFAULT_NAME, DOMAIN


@pytest.fixture(autouse=True)
def mock_client_session():
    with (
        patch(
            "custom_components.ha_cellular_gateway.config_flow.async_get_clientsession",
            return_value=object(),
        ),
        patch(
            "custom_components.ha_cellular_gateway.async_get_clientsession",
            return_value=object(),
        ),
    ):
        yield


async def test_user_step_shows_form(hass) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_user_step_creates_entry(hass) -> None:
    with patch(
        "custom_components.ha_cellular_gateway.api.GatewayApi.status",
        AsyncMock(return_value={}),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
            data={CONF_URL: "http://gateway.local:8099/", CONF_TOKEN: "token"},
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == DEFAULT_NAME
    assert result["data"] == {
        CONF_URL: "http://gateway.local:8099",
        CONF_TOKEN: "token",
    }
    created_entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert created_entry.unique_id == "http://gateway.local:8099"
    assert await hass.config_entries.async_unload(created_entry.entry_id)
    await hass.async_block_till_done()


async def test_user_step_reports_cannot_connect(hass) -> None:
    with patch(
        "custom_components.ha_cellular_gateway.api.GatewayApi.status",
        AsyncMock(side_effect=GatewayApiError("offline")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
            data={CONF_URL: "http://gateway.local:8099", CONF_TOKEN: "token"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_step_updates_existing_entry_for_normalized_url(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="gateway-uuid",
        data={CONF_URL: "http://gateway.local:8099", CONF_TOKEN: "old-token"},
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.ha_cellular_gateway.api.GatewayApi.status",
            AsyncMock(return_value={}),
        ),
        patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)) as reload_entry,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
            data={CONF_URL: "http://gateway.local:8099/", CONF_TOKEN: "new-token"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data == {
        CONF_URL: "http://gateway.local:8099",
        CONF_TOKEN: "new-token",
    }
    reload_entry.assert_awaited_once_with(entry.entry_id)


async def test_user_step_rejects_second_distinct_gateway(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="gateway-uuid",
        data={CONF_URL: "http://gateway.local:8099", CONF_TOKEN: "token"},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.ha_cellular_gateway.api.GatewayApi.status",
        AsyncMock(return_value={}),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "user"},
            data={CONF_URL: "http://other-gateway.local:8099", CONF_TOKEN: "token"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_hassio_step_creates_entry(hass) -> None:
    with patch(
        "custom_components.ha_cellular_gateway.api.GatewayApi.status",
        AsyncMock(return_value={}),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_HASSIO},
            data=HassioServiceInfo(
                config={"host": "gateway.local", "port": 8099, "token": "token"},
                name="Gateway",
                slug="ha-cellular-gateway",
                uuid="gateway-uuid",
            ),
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Gateway"
    assert result["data"] == {
        CONF_URL: "http://gateway.local:8099",
        CONF_TOKEN: "token",
    }
    created_entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert await hass.config_entries.async_unload(created_entry.entry_id)
    await hass.async_block_till_done()


async def test_hassio_step_aborts_when_validation_fails(hass) -> None:
    with patch(
        "custom_components.ha_cellular_gateway.api.GatewayApi.status",
        AsyncMock(side_effect=GatewayApiError("offline")),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_HASSIO},
            data=HassioServiceInfo(
                config={"host": "gateway.local", "port": 8099, "token": "token"},
                name="Gateway",
                slug="ha-cellular-gateway",
                uuid="gateway-uuid",
            ),
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_hassio_step_validation_failure_does_not_update_existing_entry(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_URL: "http://gateway.local:8099", CONF_TOKEN: "old-token"},
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.ha_cellular_gateway.api.GatewayApi.status",
            AsyncMock(side_effect=GatewayApiError("offline")),
        ),
        patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)) as reload_entry,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_HASSIO},
            data=HassioServiceInfo(
                config={"host": "gateway.local", "port": 8099, "token": "new-token"},
                name="Gateway",
                slug="ha-cellular-gateway",
                uuid="gateway-uuid",
            ),
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"
    assert entry.unique_id is None
    assert entry.data == {
        CONF_URL: "http://gateway.local:8099",
        CONF_TOKEN: "old-token",
    }
    reload_entry.assert_not_awaited()


async def test_hassio_step_updates_existing_manual_entry(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_URL: "http://gateway.local:8099/", CONF_TOKEN: "old-token"},
    )
    entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.ha_cellular_gateway.api.GatewayApi.status",
            AsyncMock(return_value={}),
        ),
        patch.object(hass.config_entries, "async_reload", AsyncMock(return_value=True)) as reload_entry,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_HASSIO},
            data=HassioServiceInfo(
                config={"host": "gateway.local", "port": 8099, "token": "new-token"},
                name="Gateway",
                slug="ha-cellular-gateway",
                uuid="gateway-uuid",
            ),
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.unique_id == "gateway-uuid"
    assert entry.data == {
        CONF_URL: "http://gateway.local:8099",
        CONF_TOKEN: "new-token",
    }
    reload_entry.assert_awaited_once_with(entry.entry_id)


async def test_hassio_step_rejects_second_distinct_gateway(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="gateway-uuid",
        data={CONF_URL: "http://gateway.local:8099", CONF_TOKEN: "token"},
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.ha_cellular_gateway.api.GatewayApi.status",
        AsyncMock(return_value={}),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_HASSIO},
            data=HassioServiceInfo(
                config={"host": "other-gateway.local", "port": 8099, "token": "token"},
                name="Gateway",
                slug="ha-cellular-gateway",
                uuid="other-gateway-uuid",
            ),
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
