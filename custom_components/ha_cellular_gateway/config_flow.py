from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .api import GatewayApi, GatewayApiError
from .const import CONF_TOKEN, DEFAULT_NAME, DOMAIN


class GatewayConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    def _normalize_url(url: str) -> str:
        return url.rstrip("/")

    def _existing_entry(self) -> ConfigEntry | None:
        return next(iter(self._async_current_entries(include_ignore=True)), None)

    def _entry_for_url(self, url: str) -> ConfigEntry | None:
        normalized_url = self._normalize_url(url)
        for entry in self._async_current_entries(include_ignore=True):
            if self._normalize_url(str(entry.data.get(CONF_URL, ""))) == normalized_url:
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
            url = self._normalize_url(user_input[CONF_URL])
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
                if self._existing_entry() is not None:
                    return self.async_abort(reason="single_instance_allowed")
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
        url = self._normalize_url(f"http://{config['host']}:{config['port']}")
        token = str(config["token"])
        try:
            await self._validate(url, token)
        except GatewayApiError:
            return self.async_abort(reason="cannot_connect")
        if entry := self._entry_for_url(url):
            return self.async_update_reload_and_abort(
                entry,
                unique_id=discovery_info.uuid,
                data_updates={CONF_URL: url, CONF_TOKEN: token},
                reload_even_if_entry_is_unchanged=False,
                reason="already_configured",
            )
        if self._existing_entry() is not None:
            return self.async_abort(reason="single_instance_allowed")
        await self.async_set_unique_id(discovery_info.uuid)
        self._abort_if_unique_id_configured(
            updates={CONF_URL: url, CONF_TOKEN: token}
        )
        return self.async_create_entry(
            title=discovery_info.name or DEFAULT_NAME,
            data={CONF_URL: url, CONF_TOKEN: token},
        )
