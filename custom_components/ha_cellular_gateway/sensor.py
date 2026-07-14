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
        key="mode",
        translation_key="mode",
        device_class=SensorDeviceClass.ENUM,
        options=["disabled", "trial", "active"],
        icon="mdi:wan",
        value_fn=lambda data: data["mode"],
    ),
    GatewaySensorEntityDescription(
        key="desired_mode",
        translation_key="desired_mode",
        device_class=SensorDeviceClass.ENUM,
        options=["disabled", "trial", "active"],
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:target",
        value_fn=lambda data: data["desired_mode"],
    ),
    GatewaySensorEntityDescription(
        key="upstream_mode",
        translation_key="upstream_mode",
        device_class=SensorDeviceClass.ENUM,
        options=["hotspot_wifi", "iphone_usb"],
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:access-point",
        value_fn=lambda data: data["upstream_mode"],
    ),
    GatewaySensorEntityDescription(
        key="upstream_pairing_state",
        translation_key="upstream_pairing_state",
        device_class=SensorDeviceClass.ENUM,
        options=[
            "not_applicable",
            "not_ready",
            "dry_run_blocked",
            "invalid_lease",
            "waiting_for_dhcp",
            "paired",
            "daemon_failed",
            "waiting_for_device",
            "multiple_devices",
            "waiting_for_interface",
            "ownership_conflict",
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

