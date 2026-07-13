from __future__ import annotations

from homeassistant.components.select import SelectEntity
from . import GatewayConfigEntry
from .entity import GatewayEntity


async def async_setup_entry(hass, entry: GatewayConfigEntry, async_add_entities) -> None:
    async_add_entities(
        [GatewayModeSelect(entry.runtime_data, entry.entry_id)]
    )


class GatewayModeSelect(GatewayEntity, SelectEntity):
    _attr_name = "Mode"
    _attr_options = ["disabled", "trial"]

    def __init__(self, coordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "mode_control")

    @property
    def current_option(self) -> str | None:
        mode = self.coordinator.data.get("mode")
        return mode if mode in self.options else None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.api.set_mode(option)
        await self.coordinator.async_request_refresh()
