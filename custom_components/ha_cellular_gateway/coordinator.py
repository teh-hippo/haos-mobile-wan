from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GatewayApi, GatewayApiAuthError, GatewayApiError
from .const import DOMAIN
from .models import GatewayIssue, GatewayStatus
from .repairs import sync_repairs

LOGGER = logging.getLogger(__name__)


class GatewayCoordinator(DataUpdateCoordinator[GatewayStatus]):
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
            logger=LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=30),
        )
        self.api = api
        self.entry_id = entry_id
        self.entry_title = entry_title
        self._repair_keys: set[str] = set()

    async def _async_update_data(self) -> GatewayStatus:
        try:
            data = await self.api.status()
        except GatewayApiAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GatewayApiError as err:
            raise UpdateFailed(str(err)) from err
        issues: list[GatewayIssue] = data.get("issues", [])
        self._repair_keys = sync_repairs(
            self.hass,
            self.entry_id,
            self.entry_title,
            self._repair_keys,
            issues,
        )
        return data

    async def async_clear_repairs(self) -> None:
        self._repair_keys = sync_repairs(
            self.hass,
            self.entry_id,
            self.entry_title,
            self._repair_keys,
            [],
        )
