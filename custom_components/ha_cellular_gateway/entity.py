from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import GatewayApiAuthError, GatewayApiConnectionError, GatewayApiError
from .const import DEFAULT_NAME, DOMAIN
from .coordinator import GatewayCoordinator


class GatewayEntity(CoordinatorEntity[GatewayCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: GatewayCoordinator, entry_id: str, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=DEFAULT_NAME,
            manufacturer="teh-hippo",
            model="HAOS Mobile WAN",
        )

    def _action_exception(self, err: GatewayApiError) -> HomeAssistantError:
        if isinstance(err, GatewayApiAuthError):
            return HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="invalid_auth",
            )
        if isinstance(err, GatewayApiConnectionError):
            return HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
            )
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="api_error",
            translation_placeholders={"error": str(err)},
        )
