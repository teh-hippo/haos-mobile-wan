from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GatewayApi, GatewayApiError
from .const import DOMAIN
from .models import GatewayStatus

LOGGER = logging.getLogger(__name__)


class GatewayCoordinator(DataUpdateCoordinator[GatewayStatus]):
    def __init__(self, hass: HomeAssistant, api: GatewayApi) -> None:
        super().__init__(
            hass,
            logger=LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
        )
        self.api = api

    async def _async_update_data(self) -> GatewayStatus:
        try:
            return await self.api.status()
        except GatewayApiError as err:
            raise UpdateFailed(str(err)) from err
