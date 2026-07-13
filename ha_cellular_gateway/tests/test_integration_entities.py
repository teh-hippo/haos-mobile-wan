import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_PATH = REPO_ROOT / "custom_components" / "ha_cellular_gateway"


def load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def install_stubs() -> None:
    for name in (
        "custom_components",
        "custom_components.ha_cellular_gateway",
        "custom_components.ha_cellular_gateway.api",
        "custom_components.ha_cellular_gateway.config_flow",
        "custom_components.ha_cellular_gateway.const",
        "custom_components.ha_cellular_gateway.entity",
        "custom_components.ha_cellular_gateway.select",
        "homeassistant",
        "homeassistant.components",
        "homeassistant.components.select",
        "homeassistant.config_entries",
        "homeassistant.const",
        "homeassistant.helpers",
        "homeassistant.helpers.aiohttp_client",
        "homeassistant.helpers.service_info",
        "homeassistant.helpers.service_info.hassio",
        "voluptuous",
    ):
        sys.modules.pop(name, None)

    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(REPO_ROOT / "custom_components")]
    sys.modules["custom_components"] = custom_components

    package = types.ModuleType("custom_components.ha_cellular_gateway")
    package.__path__ = [str(PACKAGE_PATH)]
    package.GatewayConfigEntry = object
    sys.modules["custom_components.ha_cellular_gateway"] = package

    voluptuous = types.ModuleType("voluptuous")
    voluptuous.Required = lambda value: value
    voluptuous.Schema = lambda value: value
    sys.modules["voluptuous"] = voluptuous

    homeassistant = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = homeassistant

    config_entries = types.ModuleType("homeassistant.config_entries")

    class ConfigEntry:
        def __class_getitem__(cls, _item):
            return cls

    class ConfigFlow:
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__()

    config_entries.ConfigEntry = ConfigEntry
    config_entries.ConfigFlow = ConfigFlow
    config_entries.ConfigFlowResult = dict
    sys.modules["homeassistant.config_entries"] = config_entries

    const = types.ModuleType("homeassistant.const")
    const.CONF_URL = "url"
    sys.modules["homeassistant.const"] = const

    gateway_const = types.ModuleType("custom_components.ha_cellular_gateway.const")
    gateway_const.CONF_TOKEN = "token"
    gateway_const.DEFAULT_NAME = "HAOS Mobile WAN"
    gateway_const.DOMAIN = "ha_cellular_gateway"
    sys.modules["custom_components.ha_cellular_gateway.const"] = gateway_const

    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    sys.modules["homeassistant.helpers"] = helpers

    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None
    sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client

    service_info = types.ModuleType("homeassistant.helpers.service_info")
    service_info.__path__ = []
    sys.modules["homeassistant.helpers.service_info"] = service_info

    hassio = types.ModuleType("homeassistant.helpers.service_info.hassio")
    hassio.HassioServiceInfo = object
    sys.modules["homeassistant.helpers.service_info.hassio"] = hassio

    components = types.ModuleType("homeassistant.components")
    components.__path__ = []
    sys.modules["homeassistant.components"] = components

    select = types.ModuleType("homeassistant.components.select")

    class SelectEntity:
        @property
        def options(self):
            return list(getattr(self, "_attr_options", []))

    select.SelectEntity = SelectEntity
    sys.modules["homeassistant.components.select"] = select

    api = types.ModuleType("custom_components.ha_cellular_gateway.api")

    class GatewayApiError(RuntimeError):
        pass

    class GatewayApi:
        def __init__(self, session, url: str, token: str) -> None:
            self.url = url
            self.token = token

        async def status(self):
            return {}

    api.GatewayApi = GatewayApi
    api.GatewayApiError = GatewayApiError
    sys.modules["custom_components.ha_cellular_gateway.api"] = api

    entity = types.ModuleType("custom_components.ha_cellular_gateway.entity")

    class GatewayEntity:
        def __init__(self, coordinator, entry_id: str, key: str) -> None:
            self.coordinator = coordinator
            self.entry_id = entry_id
            self.key = key

    entity.GatewayEntity = GatewayEntity
    sys.modules["custom_components.ha_cellular_gateway.entity"] = entity


class GatewayIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_stubs()
        cls.config_flow = load_module(
            "custom_components.ha_cellular_gateway.config_flow",
            PACKAGE_PATH / "config_flow.py",
        )
        cls.select = load_module(
            "custom_components.ha_cellular_gateway.select",
            PACKAGE_PATH / "select.py",
        )

    def make_flow(self):
        flow = self.config_flow.GatewayConfigFlow()
        flow.hass = object()
        flow.async_abort = lambda **kwargs: kwargs
        flow.async_create_entry = lambda **kwargs: kwargs
        flow.async_show_form = lambda **kwargs: kwargs
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = lambda **kwargs: None
        return flow

    def test_manual_entry_deduplicates_normalized_url(self) -> None:
        flow = self.make_flow()
        entry = SimpleNamespace(data={"url": "http://gateway.local:8099"})
        flow._async_current_entries = lambda include_ignore=True: [entry]
        flow._validate = AsyncMock()
        flow.async_update_reload_and_abort = lambda existing, **kwargs: {
            "entry": existing,
            **kwargs,
        }

        result = asyncio.run(
            flow.async_step_user({"url": "http://gateway.local:8099/", "token": "abc"})
        )

        flow._validate.assert_awaited_once_with("http://gateway.local:8099", "abc")
        self.assertIs(result["entry"], entry)
        self.assertEqual(
            result["data_updates"],
            {"url": "http://gateway.local:8099", "token": "abc"},
        )

    def test_hassio_discovery_does_not_replace_manual_entry_on_validation_failure(
        self,
    ) -> None:
        flow = self.make_flow()
        entry = SimpleNamespace(data={"url": "http://gateway.local:8099"})
        flow._async_current_entries = lambda include_ignore=True: [entry]
        flow._validate = AsyncMock(
            side_effect=self.config_flow.GatewayApiError("cannot_connect")
        )
        flow.async_update_reload_and_abort = AsyncMock()

        result = asyncio.run(
            flow.async_step_hassio(
                SimpleNamespace(
                    config={
                        "host": "gateway.local",
                        "port": 8099,
                        "token": "stale-token",
                    },
                    uuid="gateway-uuid",
                    name="Gateway",
                )
            )
        )

        self.assertEqual(result, {"reason": "cannot_connect"})
        flow.async_update_reload_and_abort.assert_not_called()

    def test_hassio_discovery_converts_existing_manual_entry(self) -> None:
        flow = self.make_flow()
        entry = SimpleNamespace(data={"url": "http://gateway.local:8099/"})
        flow._async_current_entries = lambda include_ignore=True: [entry]
        calls: list[str] = []

        async def validate(url: str, token: str) -> None:
            calls.append("validate")
            self.assertEqual(url, "http://gateway.local:8099")
            self.assertEqual(token, "fresh-token")

        flow._validate = validate

        def update(existing, **kwargs):
            calls.append("update")
            self.assertIs(existing, entry)
            return kwargs

        flow.async_update_reload_and_abort = update

        result = asyncio.run(
            flow.async_step_hassio(
                SimpleNamespace(
                    config={
                        "host": "gateway.local",
                        "port": 8099,
                        "token": "fresh-token",
                    },
                    uuid="gateway-uuid",
                    name="Gateway",
                )
            )
        )

        self.assertEqual(calls, ["validate", "update"])
        self.assertEqual(result["unique_id"], "gateway-uuid")
        self.assertEqual(
            result["data_updates"],
            {"url": "http://gateway.local:8099", "token": "fresh-token"},
        )
        self.assertEqual(result["reason"], "already_configured")

    def test_mode_select_only_exposes_supported_actions(self) -> None:
        coordinator = SimpleNamespace(
            data={"mode": "active"},
            api=SimpleNamespace(set_mode=AsyncMock()),
            async_request_refresh=AsyncMock(),
        )
        entity = self.select.GatewayModeSelect(coordinator, "entry-1")

        self.assertEqual(entity.options, ["disabled", "trial"])
        self.assertIsNone(entity.current_option)

        asyncio.run(entity.async_select_option("trial"))

        coordinator.api.set_mode.assert_awaited_once_with("trial")
        coordinator.async_request_refresh.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
