from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GatewayConfigEntry
from .coordinator import GatewayCoordinator
from .entity import GatewayEntity
from .models import GatewayStatus

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class GatewayBinarySensorEntityDescription(BinarySensorEntityDescription):
    value_fn: Callable[[GatewayStatus], bool]


DESCRIPTIONS = (
    GatewayBinarySensorEntityDescription(
        key="upstream_healthy",
        translation_key="upstream_healthy",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data["upstream_healthy"],
    ),
    GatewayBinarySensorEntityDescription(
        key="downstream_present",
        translation_key="downstream_present",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:ethernet",
        value_fn=lambda data: data["downstream_present"],
    ),
    GatewayBinarySensorEntityDescription(
        key="rules_installed",
        translation_key="rules_installed",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:firewall",
        value_fn=lambda data: data["rules_installed"],
    ),
    GatewayBinarySensorEntityDescription(
        key="dnsmasq_running",
        translation_key="dnsmasq_running",
        device_class=BinarySensorDeviceClass.RUNNING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:server-network",
        value_fn=lambda data: data["dnsmasq_running"],
    ),
    GatewayBinarySensorEntityDescription(
        key="rollback_armed",
        translation_key="rollback_armed",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:timer-alert-outline",
        value_fn=lambda data: data["rollback_armed"],
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GatewayConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        GatewayBinarySensor(entry.runtime_data, entry.entry_id, description)
        for description in DESCRIPTIONS
    )
    async_add_entities(
        [GatewaySafetySensor(entry.runtime_data, entry.entry_id)]
    )


class GatewayBinarySensor(GatewayEntity, BinarySensorEntity):
    entity_description: GatewayBinarySensorEntityDescription
    def __init__(
        self,
        coordinator: GatewayCoordinator,
        entry_id: str,
        description: GatewayBinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, entry_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return self.entity_description.value_fn(self.coordinator.data)


class GatewaySafetySensor(GatewayEntity, BinarySensorEntity):
    _attr_translation_key = "safety_checks"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GatewayCoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "safety_checks")

    @property
    def is_on(self) -> bool:
        return not self.coordinator.data["safety_errors"]

    @property
    def extra_state_attributes(self) -> dict[str, list[str]]:
        return {"errors": self.coordinator.data["safety_errors"]}

    @property
    def icon(self) -> str:
        return "mdi:shield-check" if self.is_on else "mdi:shield-alert"
