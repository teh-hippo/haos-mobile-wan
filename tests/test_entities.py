from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.binary_sensor import BinarySensorEntityDescription
from homeassistant.components.button import ButtonEntityDescription
from homeassistant.components.sensor import SensorEntityDescription

from custom_components.ha_cellular_gateway import binary_sensor, button, entity, select, sensor


async def test_binary_sensor_setup_and_state(runtime_coordinator) -> None:
    created: list[Any] = []
    entry_obj = type(
        "Entry",
        (),
        {"runtime_data": runtime_coordinator, "entry_id": "entry-1"},
    )()

    await binary_sensor.async_setup_entry(None, entry_obj, created.extend)

    assert len(created) == 6
    assert created[0].is_on is True
    assert created[-1].is_on is True
    assert created[-1].extra_state_attributes == {"errors": []}


async def test_binary_sensor_false_and_safety_errors(runtime_coordinator) -> None:
    runtime_coordinator.data["upstream_healthy"] = False
    runtime_coordinator.data["safety_errors"] = ["missing upstream"]
    regular = binary_sensor.GatewayBinarySensor(
        runtime_coordinator,
        "entry-1",
        BinarySensorEntityDescription(key="upstream_healthy", name="Cellular upstream"),
    )
    safety = binary_sensor.GatewaySafetySensor(runtime_coordinator, "entry-1")

    assert regular.is_on is False
    assert safety.is_on is False
    assert safety.extra_state_attributes == {"errors": ["missing upstream"]}


async def test_button_setup_and_press(runtime_coordinator) -> None:
    created: list[Any] = []
    entry_obj = type(
        "Entry",
        (),
        {"runtime_data": runtime_coordinator, "entry_id": "entry-1"},
    )()

    await button.async_setup_entry(None, entry_obj, created.extend)
    await created[0].async_press()

    runtime_coordinator.api.reconcile.assert_awaited_once_with()
    runtime_coordinator.async_request_refresh.assert_awaited_once_with()


async def test_select_setup_and_action(runtime_coordinator) -> None:
    created: list[Any] = []
    entry_obj = type(
        "Entry",
        (),
        {"runtime_data": runtime_coordinator, "entry_id": "entry-1"},
    )()

    await select.async_setup_entry(None, entry_obj, created.extend)

    assert created[0].current_option is None
    assert created[0].options == ["disabled", "trial"]
    await created[0].async_select_option("trial")
    runtime_coordinator.api.set_mode.assert_awaited_once_with("trial")


async def test_sensor_setup_and_values(runtime_coordinator) -> None:
    created: list[Any] = []
    entry_obj = type(
        "Entry",
        (),
        {"runtime_data": runtime_coordinator, "entry_id": "entry-1"},
    )()

    await sensor.async_setup_entry(None, entry_obj, created.extend)

    assert len(created) == len(sensor.DESCRIPTIONS)
    assert created[0].native_value == "active"
    runtime_coordinator.data["mode"] = None
    assert created[0].native_value is None


async def test_gateway_entity_sets_device_metadata(runtime_coordinator) -> None:
    gateway_entity = entity.GatewayEntity(runtime_coordinator, "entry-1", "mode")

    assert gateway_entity.unique_id == "entry-1_mode"
    assert gateway_entity.has_entity_name is True
    assert gateway_entity.device_info["name"] == "HAOS Mobile WAN"
    assert gateway_entity.device_info["manufacturer"] == "teh-hippo"


async def test_button_and_sensor_entity_names(runtime_coordinator) -> None:
    gateway_button = button.GatewayButton(
        runtime_coordinator,
        "entry-1",
        ButtonEntityDescription(key="reconcile", name="Reapply gateway state"),
    )
    gateway_sensor = sensor.GatewaySensor(
        runtime_coordinator,
        "entry-1",
        SensorEntityDescription(key="mode", name="Mode"),
    )

    assert gateway_button.name == "Reapply gateway state"
    assert gateway_sensor.name == "Mode"


async def test_button_press_raises_translated_auth_error(runtime_coordinator) -> None:
    from homeassistant.exceptions import HomeAssistantError
    from custom_components.ha_cellular_gateway.api import GatewayApiAuthError
    from homeassistant.components.button import ButtonEntityDescription

    runtime_coordinator.api.reconcile = AsyncMock(
        side_effect=GatewayApiAuthError("bad token")
    )

    gateway_button = button.GatewayButton(
        runtime_coordinator,
        "entry-1",
        ButtonEntityDescription(key="reconcile", name="Reapply gateway state"),
    )

    with pytest.raises(HomeAssistantError) as exc_info:
        await gateway_button.async_press()

    assert exc_info.value.translation_domain == "ha_cellular_gateway"
    assert exc_info.value.translation_key == "invalid_auth"
    runtime_coordinator.async_request_refresh.assert_not_awaited()


async def test_select_raises_translated_api_error(runtime_coordinator) -> None:
    from homeassistant.exceptions import HomeAssistantError
    from custom_components.ha_cellular_gateway.api import GatewayApiError

    runtime_coordinator.api.set_mode = AsyncMock(
        side_effect=GatewayApiError("mode change rejected")
    )

    gateway_select = select.GatewayModeSelect(runtime_coordinator, "entry-1")

    with pytest.raises(HomeAssistantError) as exc_info:
        await gateway_select.async_select_option("trial")

    assert exc_info.value.translation_domain == "ha_cellular_gateway"
    assert exc_info.value.translation_key == "api_error"
    assert exc_info.value.translation_placeholders == {"error": "mode change rejected"}
    runtime_coordinator.async_request_refresh.assert_not_awaited()


async def test_button_press_raises_translated_connection_error(runtime_coordinator) -> None:
    from homeassistant.exceptions import HomeAssistantError
    from custom_components.ha_cellular_gateway.api import GatewayApiConnectionError
    from homeassistant.components.button import ButtonEntityDescription

    runtime_coordinator.api.reconcile = AsyncMock(
        side_effect=GatewayApiConnectionError("offline")
    )

    gateway_button = button.GatewayButton(
        runtime_coordinator,
        "entry-1",
        ButtonEntityDescription(key="reconcile", name="Reapply gateway state"),
    )

    with pytest.raises(HomeAssistantError) as exc_info:
        await gateway_button.async_press()

    assert exc_info.value.translation_domain == "ha_cellular_gateway"
    assert exc_info.value.translation_key == "cannot_connect"
    runtime_coordinator.async_request_refresh.assert_not_awaited()
