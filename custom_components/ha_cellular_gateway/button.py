from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription

from . import GatewayConfigEntry
from .entity import GatewayEntity


@dataclass(frozen=True, kw_only=True)
class GatewayButtonEntityDescription(ButtonEntityDescription):
    action: str


DESCRIPTIONS = (
    GatewayButtonEntityDescription(
        key="reconcile",
        name="Reconcile",
        action="reconcile",
    ),
    GatewayButtonEntityDescription(
        key="seek_hotspot",
        name="Scan for hotspot",
        action="seek",
    ),
)


async def async_setup_entry(hass, entry: GatewayConfigEntry, async_add_entities) -> None:
    async_add_entities(
        GatewayButton(entry.runtime_data, entry.entry_id, description)
        for description in DESCRIPTIONS
    )


class GatewayButton(GatewayEntity, ButtonEntity):
    def __init__(
        self,
        coordinator,
        entry_id: str,
        description: GatewayButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator, entry_id, description.key)
        self.entity_description = description
        self._attr_name = description.name

    async def async_press(self) -> None:
        if self.entity_description.action == "reconcile":
            await self.coordinator.api.reconcile()
        else:
            await self.coordinator.api.seek()
        await self.coordinator.async_request_refresh()
