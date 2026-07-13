from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data

from . import GatewayConfigEntry
from .const import CONF_TOKEN


TO_REDACT = {
    CONF_TOKEN,
    "public_ip",
    "upstream_address",
    "upstream_gateway",
    "upstream_ssid",
    "downstream_mac",
}


async def async_get_config_entry_diagnostics(hass, entry: GatewayConfigEntry):
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "status": async_redact_data(dict(entry.runtime_data.data), TO_REDACT),
    }
