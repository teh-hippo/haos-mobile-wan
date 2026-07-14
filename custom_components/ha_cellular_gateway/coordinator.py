from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GatewayApi, GatewayApiAuthError, GatewayApiError
from .const import DOMAIN


class GatewayCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, api: GatewayApi) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.api.status()
        except GatewayApiAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GatewayApiError as err:
            raise UpdateFailed(str(err)) from err
