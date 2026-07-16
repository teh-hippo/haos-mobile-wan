from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GatewayConfigEntry
from .coordinator import GatewayCoordinator
from .entity import GatewayEntity
from .models import GatewayStatus

PARALLEL_UPDATES = 0

GatewaySensorValue = str | None


@dataclass(frozen=True, kw_only=True)
class GatewaySensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[GatewayStatus], GatewaySensorValue]


DESCRIPTIONS = (
    GatewaySensorEntityDescription(
        key="mobile_connection",
        translation_key="mobile_connection",
        device_class=SensorDeviceClass.ENUM,
        options=[
            "wifi_hotspot",
            "iphone_usb",
            "iphone_usb_wifi_fallback",
        ],
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:connection",
        value_fn=lambda data: data["mobile_connection"],
    ),
    GatewaySensorEntityDescription(
        key="active_connection",
        translation_key="active_connection",
        device_class=SensorDeviceClass.ENUM,
        options=["wifi_hotspot", "iphone_usb"],
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:access-point",
        value_fn=lambda data: data["active_connection"],
    ),
    GatewaySensorEntityDescription(
        key="upstream_pairing_state",
        translation_key="upstream_pairing_state",
        device_class=SensorDeviceClass.ENUM,
        options=[
            "not_applicable",
            "not_ready",
            "waiting_for_device",
            "multiple_devices",
            "waiting_for_interface",
            "waiting_for_trust",
            "waiting_for_unlock",
            "pairing_failed",
            "daemon_failed",
            "profile_failed",
            "waiting_for_profile",
            "profile_conflict",
            "invalid_lease",
            "paired",
        ],
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:usb-port",
        value_fn=lambda data: data["upstream_pairing_state"],
    ),
    GatewaySensorEntityDescription(
        key="downstream_interface",
        translation_key="downstream_interface",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:ethernet",
        value_fn=lambda data: data["downstream_interface"],
    ),
    GatewaySensorEntityDescription(
        key="public_ip",
        translation_key="public_ip",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:ip-network-outline",
        value_fn=lambda data: data["public_ip"],
    ),
    GatewaySensorEntityDescription(
        key="last_error",
        translation_key="last_error",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:alert-circle-outline",
        value_fn=lambda data: data["last_error"],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GatewayConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        GatewaySensor(entry.runtime_data, entry.entry_id, description)
        for description in DESCRIPTIONS
    )


class GatewaySensor(GatewayEntity, SensorEntity):
    entity_description: GatewaySensorEntityDescription

    def __init__(
        self,
        coordinator: GatewayCoordinator,
        entry_id: str,
        description: GatewaySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, entry_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> GatewaySensorValue:
        return self.entity_description.value_fn(self.coordinator.data)
