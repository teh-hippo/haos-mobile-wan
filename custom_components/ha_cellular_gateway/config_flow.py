from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .api import GatewayApi, GatewayApiError
from .const import CONF_TOKEN, DEFAULT_NAME, DOMAIN


class GatewayConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def _entry_for_url(self, url: str):
        for entry in self._async_current_entries(include_ignore=True):
            if entry.data.get(CONF_URL) == url:
                return entry
        return None

    async def _validate(self, url: str, token: str) -> None:
        api = GatewayApi(async_get_clientsession(self.hass), url, token)
        await api.status()

    async def async_step_user(
        self,
        user_input: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            token = user_input[CONF_TOKEN]
            try:
                await self._validate(url, token)
            except GatewayApiError:
                errors["base"] = "cannot_connect"
            else:
                if entry := self._entry_for_url(url):
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={CONF_URL: url, CONF_TOKEN: token},
                    )
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=DEFAULT_NAME,
                    data={CONF_URL: url, CONF_TOKEN: token},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL): str,
                    vol.Required(CONF_TOKEN): str,
                }
            ),
            errors=errors,
        )

    async def async_step_hassio(
        self,
        discovery_info: HassioServiceInfo,
    ) -> ConfigFlowResult:
        config: dict[str, Any] = discovery_info.config
        url = f"http://{config['host']}:{config['port']}"
        token = str(config["token"])
        if entry := self._entry_for_url(url):
            return self.async_update_reload_and_abort(
                entry,
                unique_id=discovery_info.uuid,
                data_updates={CONF_URL: url, CONF_TOKEN: token},
                reload_even_if_entry_is_unchanged=False,
                reason="already_configured",
            )
        await self.async_set_unique_id(discovery_info.uuid)
        self._abort_if_unique_id_configured(
            updates={CONF_URL: url, CONF_TOKEN: token}
        )
        try:
            await self._validate(url, token)
        except GatewayApiError:
            return self.async_abort(reason="cannot_connect")
        return self.async_create_entry(
            title=discovery_info.name or DEFAULT_NAME,
            data={CONF_URL: url, CONF_TOKEN: token},
        )
