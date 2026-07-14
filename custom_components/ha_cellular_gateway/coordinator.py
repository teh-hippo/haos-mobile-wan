from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GatewayApi, GatewayApiError
from .const import DOMAIN
from .repairs import sync_repairs


class GatewayCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        api: GatewayApi,
        *,
        entry_id: str,
        entry_title: str,
    ) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
        )
        self.api = api
        self.entry_id = entry_id
        self.entry_title = entry_title
        self._repair_keys: set[str] = set()

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.api.status()
        except GatewayApiError as err:
            raise UpdateFailed(str(err)) from err
        self._repair_keys = sync_repairs(
            self.hass,
            self.entry_id,
            self.entry_title,
            self._repair_keys,
            data,
        )
        return data

    async def async_clear_repairs(self) -> None:
        self._repair_keys = sync_repairs(
            self.hass,
            self.entry_id,
            self.entry_title,
            self._repair_keys,
            {},
        )
