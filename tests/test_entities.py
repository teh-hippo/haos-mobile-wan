from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from homeassistant.components.button import ButtonEntityDescription
from homeassistant.helpers.entity import EntityCategory

from custom_components.ha_cellular_gateway import (
    binary_sensor,
    button,
    entity,
    sensor,
    switch,
)
from custom_components.ha_cellular_gateway.binary_sensor import GatewayBinarySensorEntityDescription


async def test_binary_sensor_setup_and_state(runtime_coordinator) -> None:
    created: list[Any] = []
    entry_obj = type(
        "Entry",
        (),
        {"runtime_data": runtime_coordinator, "entry_id": "entry-1"},
    )()

    await binary_sensor.async_setup_entry(None, entry_obj, created.extend)

    assert len(created) == 5
    assert created[0].is_on is True
    assert created[-1].is_on is True
    assert created[-1].extra_state_attributes == {"errors": []}


async def test_binary_sensor_false_and_safety_errors(runtime_coordinator) -> None:
    runtime_coordinator.data["upstream_healthy"] = False
    runtime_coordinator.data["safety_errors"] = ["missing upstream"]
    regular = binary_sensor.GatewayBinarySensor(
        runtime_coordinator,
        "entry-1",
        GatewayBinarySensorEntityDescription(
            key="upstream_healthy",
            translation_key="upstream_healthy",
            value_fn=lambda data: data["upstream_healthy"],
        ),
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


async def test_switch_setup_and_action(runtime_coordinator) -> None:
    created: list[Any] = []
    entry_obj = type(
        "Entry",
        (),
        {"runtime_data": runtime_coordinator, "entry_id": "entry-1"},
    )()

    await switch.async_setup_entry(None, entry_obj, created.extend)

    assert created[0].is_on is True
    await created[0].async_turn_off()
    runtime_coordinator.api.set_enabled.assert_awaited_once_with(False)


async def test_switch_reflects_disabled_state(runtime_coordinator) -> None:
    runtime_coordinator.data["enabled"] = False
    gateway_switch = switch.GatewayEnabledSwitch(runtime_coordinator, "entry-1")
    assert gateway_switch.is_on is False


async def test_sensor_setup_and_values(runtime_coordinator) -> None:
    created: list[Any] = []
    entry_obj = type(
        "Entry",
        (),
        {"runtime_data": runtime_coordinator, "entry_id": "entry-1"},
    )()

    await sensor.async_setup_entry(None, entry_obj, created.extend)

    assert len(created) == len(sensor.DESCRIPTIONS)
    assert created[0].native_value == "iphone_usb_wifi_fallback"
    runtime_coordinator.data["mobile_connection"] = None
    assert created[0].native_value is None


async def test_gateway_entity_sets_device_metadata(runtime_coordinator) -> None:
    gateway_entity = entity.GatewayEntity(
        runtime_coordinator,
        "entry-1",
        "mobile_connection",
    )

    assert gateway_entity.unique_id == "entry-1_mobile_connection"
    assert gateway_entity.has_entity_name is True
    assert gateway_entity.device_info["name"] == "HAOS Mobile WAN"
    assert gateway_entity.device_info["manufacturer"] == "teh-hippo"

    assert switch.GatewayEnabledSwitch(runtime_coordinator, "entry-1").unique_id == "entry-1_enabled"
    assert binary_sensor.GatewaySafetySensor(runtime_coordinator, "entry-1").unique_id == "entry-1_safety_checks"
    assert button.GatewayButton(runtime_coordinator, "entry-1", button.DESCRIPTIONS[0]).unique_id == "entry-1_reconcile"


async def test_entity_description_metadata(runtime_coordinator) -> None:
    sensor_desc_by_key = {d.key: d for d in sensor.DESCRIPTIONS}

    assert sensor_desc_by_key["mobile_connection"].options == [
        "wifi_hotspot",
        "iphone_usb",
        "iphone_usb_wifi_fallback",
    ]
    assert sensor_desc_by_key["active_connection"].options == [
        "wifi_hotspot",
        "iphone_usb",
    ]
    assert sensor_desc_by_key["upstream_pairing_state"].options == [
        "not_applicable",
        "not_ready",
        "invalid_lease",
        "waiting_for_dhcp",
        "paired",
        "daemon_failed",
        "waiting_for_device",
        "multiple_devices",
        "waiting_for_interface",
        "ownership_conflict",
        "waiting_for_trust",
        "waiting_for_unlock",
        "pairing_failed",
    ]
    assert sensor_desc_by_key["mobile_connection"].entity_registry_enabled_default is False
    assert sensor_desc_by_key["public_ip"].entity_registry_enabled_default is False

    enabled_switch = switch.GatewayEnabledSwitch(runtime_coordinator, "entry-1")
    assert enabled_switch._attr_translation_key == "enabled"
    assert enabled_switch._attr_entity_category == EntityCategory.CONFIG

    assert button.DESCRIPTIONS[0].translation_key == "reconcile"
    assert button.DESCRIPTIONS[0].entity_category == EntityCategory.DIAGNOSTIC
    assert button.DESCRIPTIONS[0].entity_registry_enabled_default is False


async def test_safety_sensor_icon_toggles(runtime_coordinator) -> None:
    safety = binary_sensor.GatewaySafetySensor(runtime_coordinator, "entry-1")

    assert safety.icon == "mdi:shield-check"

    runtime_coordinator.data["safety_errors"] = ["missing route"]
    assert safety.icon == "mdi:shield-alert"


async def test_button_press_raises_translated_auth_error(runtime_coordinator) -> None:
    from homeassistant.exceptions import HomeAssistantError
    from custom_components.ha_cellular_gateway.api import GatewayApiAuthError

    runtime_coordinator.api.reconcile = AsyncMock(
        side_effect=GatewayApiAuthError("bad token")
    )

    gateway_button = button.GatewayButton(
        runtime_coordinator,
        "entry-1",
        button.DESCRIPTIONS[0],
    )

    with pytest.raises(HomeAssistantError) as exc_info:
        await gateway_button.async_press()

    assert exc_info.value.translation_domain == "ha_cellular_gateway"
    assert exc_info.value.translation_key == "invalid_auth"
    runtime_coordinator.async_request_refresh.assert_not_awaited()


async def test_switch_raises_translated_api_error(runtime_coordinator) -> None:
    from homeassistant.exceptions import HomeAssistantError
    from custom_components.ha_cellular_gateway.api import GatewayApiError

    runtime_coordinator.api.set_enabled = AsyncMock(
        side_effect=GatewayApiError("enabled change rejected")
    )

    enabled_switch = switch.GatewayEnabledSwitch(runtime_coordinator, "entry-1")

    with pytest.raises(HomeAssistantError) as exc_info:
        await enabled_switch.async_turn_on()

    assert exc_info.value.translation_domain == "ha_cellular_gateway"
    assert exc_info.value.translation_key == "api_error"
    assert exc_info.value.translation_placeholders == {
        "error": "enabled change rejected"
    }
    runtime_coordinator.async_request_refresh.assert_awaited_once_with()


async def test_button_press_raises_translated_connection_error(runtime_coordinator) -> None:
    from homeassistant.exceptions import HomeAssistantError
    from custom_components.ha_cellular_gateway.api import GatewayApiConnectionError

    runtime_coordinator.api.reconcile = AsyncMock(
        side_effect=GatewayApiConnectionError("offline")
    )

    gateway_button = button.GatewayButton(
        runtime_coordinator,
        "entry-1",
        button.DESCRIPTIONS[0],
    )

    with pytest.raises(HomeAssistantError) as exc_info:
        await gateway_button.async_press()

    assert exc_info.value.translation_domain == "ha_cellular_gateway"
    assert exc_info.value.translation_key == "cannot_connect"
    runtime_coordinator.async_request_refresh.assert_not_awaited()
