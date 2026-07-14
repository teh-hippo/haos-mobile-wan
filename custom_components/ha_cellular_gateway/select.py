from __future__ import annotations

from typing import cast

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GatewayConfigEntry
from .coordinator import GatewayCoordinator
from .entity import GatewayEntity
from .models import GatewaySelectableMode

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GatewayConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        [GatewayModeSelect(entry.runtime_data, entry.entry_id)]
    )


class GatewayModeSelect(GatewayEntity, SelectEntity):
    _attr_translation_key = "mode_control"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:wan"
    _attr_options = ["disabled", "trial"]

    def __init__(self, coordinator: GatewayCoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "mode_control")

    @property
    def current_option(self) -> GatewaySelectableMode | None:
        mode = self.coordinator.data["mode"]
        if mode in self.options:
            return cast(GatewaySelectableMode, mode)
        return None

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise ValueError(f"Unsupported mode: {option}")
        await self.coordinator.api.set_mode(cast(GatewaySelectableMode, option))
        await self.coordinator.async_request_refresh()
