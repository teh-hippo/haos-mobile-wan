from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from homeassistant.components.button import ButtonEntityDescription
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.helpers.entity import EntityCategory

from custom_components.ha_cellular_gateway import binary_sensor, button, entity, select, sensor
from custom_components.ha_cellular_gateway.binary_sensor import GatewayBinarySensorEntityDescription


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
        GatewayBinarySensorEntityDescription(
            key="upstream_healthy",
            name="Cellular upstream",
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

    runtime_coordinator.data["mode"] = "trial"
    assert created[0].current_option == "trial"

    await created[0].async_select_option("trial")
    runtime_coordinator.api.set_mode.assert_awaited_once_with("trial")

    with pytest.raises(ValueError, match="Unsupported mode"):
        await created[0].async_select_option("active")


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


def test_entity_description_metadata(runtime_coordinator) -> None:
    binary_descriptions = {d.key: d for d in binary_sensor.DESCRIPTIONS}
    sensor_descriptions = {d.key: d for d in sensor.DESCRIPTIONS}
    button_description = button.DESCRIPTIONS[0]

    assert binary_descriptions["upstream_healthy"].translation_key == "upstream_healthy"
    assert not isinstance(binary_descriptions["upstream_healthy"].name, str)
    assert binary_descriptions["upstream_healthy"].device_class is not None
    assert binary_descriptions["rules_installed"].entity_registry_enabled_default is False
    assert binary_descriptions["dnsmasq_running"].icon == "mdi:server-network"

    assert sensor_descriptions["mode"].translation_key == "mode"
    assert not isinstance(sensor_descriptions["mode"].name, str)
    assert sensor_descriptions["mode"].options == ["disabled", "trial", "active"]
    assert sensor_descriptions["public_ip"].entity_registry_enabled_default is False
    assert sensor_descriptions["upstream_pairing_state"].icon == "mdi:usb-port"

    assert button_description.translation_key == "reconcile"
    assert not isinstance(button_description.name, str)
    assert button_description.entity_registry_enabled_default is False

    mode_select = select.GatewayModeSelect(runtime_coordinator, "entry-1")
    assert mode_select.translation_key == "mode_control"
    assert mode_select.entity_category == EntityCategory.CONFIG


async def test_safety_sensor_icon_toggles(runtime_coordinator) -> None:
    safety_ok = binary_sensor.GatewaySafetySensor(runtime_coordinator, "entry-1")
    assert safety_ok.is_on is True
    assert safety_ok.icon == "mdi:shield-check"

    runtime_coordinator.data["safety_errors"] = ["missing route"]
    assert safety_ok.is_on is False
    assert safety_ok.icon == "mdi:shield-alert"
