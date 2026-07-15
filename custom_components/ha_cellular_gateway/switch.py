from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GatewayConfigEntry
from .api import GatewayApiError
from .coordinator import GatewayCoordinator
from .entity import GatewayEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GatewayConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        [GatewayEnabledSwitch(entry.runtime_data, entry.entry_id)]
    )


class GatewayEnabledSwitch(GatewayEntity, SwitchEntity):
    _attr_translation_key = "enabled"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:wan"

    def __init__(self, coordinator: GatewayCoordinator, entry_id: str) -> None:
        super().__init__(coordinator, entry_id, "enabled")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data["enabled"]

    async def async_turn_on(self, **kwargs: object) -> None:
        await self._async_set_enabled(True)

    async def async_turn_off(self, **kwargs: object) -> None:
        await self._async_set_enabled(False)

    async def _async_set_enabled(self, enabled: bool) -> None:
        try:
            await self.coordinator.api.set_enabled(enabled)
        except GatewayApiError as err:
            await self.coordinator.async_request_refresh()
            raise self._action_exception(err) from err
        await self.coordinator.async_request_refresh()
