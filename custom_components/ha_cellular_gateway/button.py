from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GatewayConfigEntry
from .coordinator import GatewayCoordinator
from .entity import GatewayEntity

PARALLEL_UPDATES = 0

DESCRIPTIONS = (
    ButtonEntityDescription(
        key="reconcile",
        translation_key="reconcile",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        icon="mdi:sync",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GatewayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        GatewayButton(entry.runtime_data, entry.entry_id, description)
        for description in DESCRIPTIONS
    )


class GatewayButton(GatewayEntity, ButtonEntity):
    def __init__(
        self,
        coordinator: GatewayCoordinator,
        entry_id: str,
        description: ButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator, entry_id, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        await self.coordinator.api.reconcile()
        await self.coordinator.async_request_refresh()
