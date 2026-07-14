from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GatewayApi
from .const import CONF_TOKEN, PLATFORMS
from .coordinator import GatewayCoordinator


type GatewayConfigEntry = ConfigEntry[GatewayCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: GatewayConfigEntry) -> bool:
    api = GatewayApi(
        async_get_clientsession(hass),
        entry.data[CONF_URL],
        entry.data[CONF_TOKEN],
    )
    coordinator = GatewayCoordinator(
        hass,
        api,
        entry_id=entry.entry_id,
        entry_title=entry.title,
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GatewayConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_clear_repairs()
    return unloaded
