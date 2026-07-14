from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.ha_cellular_gateway.api import GatewayApiError
from custom_components.ha_cellular_gateway.coordinator import GatewayCoordinator


async def test_coordinator_updates_data(hass, status_payload: dict[str, object]) -> None:
    api = type("Api", (), {"status": AsyncMock(return_value=status_payload)})()
    coordinator = GatewayCoordinator(hass, api, entry_id="test", entry_title="Test")

    result = await coordinator._async_update_data()

    assert result == status_payload


async def test_coordinator_wraps_gateway_errors(hass) -> None:
    api = type(
        "Api",
        (),
        {"status": AsyncMock(side_effect=GatewayApiError("offline"))},
    )()
    coordinator = GatewayCoordinator(hass, api, entry_id="test", entry_title="Test")

    with pytest.raises(UpdateFailed, match="offline"):
        await coordinator._async_update_data()
