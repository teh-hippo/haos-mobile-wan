from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription

from . import GatewayConfigEntry
from .entity import GatewayEntity


DESCRIPTIONS = (
    SensorEntityDescription(key="mode", name="Mode"),
    SensorEntityDescription(key="desired_mode", name="Desired mode"),
    SensorEntityDescription(key="downstream_interface", name="Downstream interface"),
    SensorEntityDescription(key="public_ip", name="Cellular public IP"),
    SensorEntityDescription(key="last_error", name="Last error"),
)


async def async_setup_entry(hass, entry: GatewayConfigEntry, async_add_entities) -> None:
    async_add_entities(
        GatewaySensor(entry.runtime_data, entry.entry_id, description)
        for description in DESCRIPTIONS
    )


class GatewaySensor(GatewayEntity, SensorEntity):
    def __init__(
        self,
        coordinator,
        entry_id: str,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, entry_id, description.key)
        self.entity_description = description
        self._attr_name = description.name

    @property
    def native_value(self):
        return self.coordinator.data.get(self.entity_description.key)
