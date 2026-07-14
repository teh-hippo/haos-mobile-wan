from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription

from .api import GatewayApiError
from . import GatewayConfigEntry
from .entity import GatewayEntity

DESCRIPTIONS = (
    ButtonEntityDescription(
        key="reconcile",
        name="Reapply gateway state",
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
        description: ButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator, entry_id, description.key)
        self.entity_description = description
        self._attr_name = description.name

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.reconcile()
        except GatewayApiError as err:
            raise self._action_exception(err) from err
        await self.coordinator.async_request_refresh()
