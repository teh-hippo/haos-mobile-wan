from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)

from . import GatewayConfigEntry
from .entity import GatewayEntity


DESCRIPTIONS = (
    BinarySensorEntityDescription(key="upstream_healthy", name="Cellular upstream"),
    BinarySensorEntityDescription(key="downstream_present", name="Downstream NIC"),
    BinarySensorEntityDescription(key="rules_installed", name="Gateway rules"),
    BinarySensorEntityDescription(key="dnsmasq_running", name="Gateway DHCP"),
    BinarySensorEntityDescription(key="rollback_armed", name="Rollback armed"),
)


async def async_setup_entry(hass, entry: GatewayConfigEntry, async_add_entities) -> None:
    async_add_entities(
        GatewayBinarySensor(entry.runtime_data, entry.entry_id, description)
        for description in DESCRIPTIONS
    )
    async_add_entities(
        [GatewaySafetySensor(entry.runtime_data, entry.entry_id)]
    )


class GatewayBinarySensor(GatewayEntity, BinarySensorEntity):
    def __init__(
        self,
        coordinator,
        entry_id: str,
        description: BinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, entry_id, description.key)
        self.entity_description = description
        self._attr_name = description.name

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get(self.entity_description.key))


class GatewaySafetySensor(GatewayEntity, BinarySensorEntity):
    _attr_name = "Safety checks"

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "safety_checks")

    @property
    def is_on(self) -> bool:
        return not self.coordinator.data.get("safety_errors")

    @property
    def extra_state_attributes(self):
        return {"errors": self.coordinator.data.get("safety_errors", [])}
