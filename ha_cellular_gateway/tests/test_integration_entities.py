import asyncio
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_PATH = REPO_ROOT / "custom_components" / "ha_cellular_gateway"


def load_module(module_name: str, path: Path, *, package: bool = False):
    spec = importlib.util.spec_from_file_location(
        module_name,
        path,
        submodule_search_locations=[str(path.parent)] if package else None,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def install_stubs() -> None:
    for name in list(sys.modules):
        if name == "custom_components" or name.startswith(
            ("custom_components.ha_cellular_gateway", "homeassistant", "voluptuous")
        ):
            sys.modules.pop(name, None)

    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(REPO_ROOT / "custom_components")]
    sys.modules["custom_components"] = custom_components

    voluptuous = types.ModuleType("voluptuous")
    voluptuous.Required = lambda value, default=None: value
    voluptuous.Schema = lambda value: value
    sys.modules["voluptuous"] = voluptuous

    aiohttp = types.ModuleType("aiohttp")

    class ClientError(Exception):
        pass

    class ClientSession:
        pass

    aiohttp.ClientError = ClientError
    aiohttp.ClientSession = ClientSession
    sys.modules["aiohttp"] = aiohttp

    homeassistant = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = homeassistant

    config_entries = types.ModuleType("homeassistant.config_entries")

    class ConfigEntry:
        def __init__(
            self,
            data: dict | None = None,
            *,
            entry_id: str = "entry-1",
            unique_id: str | None = None,
            title: str = "HAOS Mobile WAN",
        ) -> None:
            self.data = data or {}
            self.entry_id = entry_id
            self.unique_id = unique_id
            self.title = title

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
    const.Platform = SimpleNamespace(
        BINARY_SENSOR="binary_sensor",
        BUTTON="button",
        SELECT="select",
        SENSOR="sensor",
    )
    sys.modules["homeassistant.const"] = const

    core = types.ModuleType("homeassistant.core")

    class HomeAssistant:
        pass

    core.HomeAssistant = HomeAssistant
    sys.modules["homeassistant.core"] = core

    exceptions = types.ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        def __init__(
            self,
            *args,
            translation_domain: str | None = None,
            translation_key: str | None = None,
            translation_placeholders: dict | None = None,
        ) -> None:
            super().__init__(*args)
            self.translation_domain = translation_domain
            self.translation_key = translation_key
            self.translation_placeholders = translation_placeholders or {}

    class ConfigEntryAuthFailed(HomeAssistantError):
        pass

    exceptions.HomeAssistantError = HomeAssistantError
    exceptions.ConfigEntryAuthFailed = ConfigEntryAuthFailed
    sys.modules["homeassistant.exceptions"] = exceptions

    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    sys.modules["homeassistant.helpers"] = helpers

    aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
    aiohttp_client.async_get_clientsession = lambda hass: None
    sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client

    selector = types.ModuleType("homeassistant.helpers.selector")

    class TextSelectorType:
        URL = "url"
        PASSWORD = "password"

    class TextSelectorConfig:
        def __init__(self, **kwargs) -> None:
            self.__dict__.update(kwargs)

    class TextSelector:
        def __init__(self, config: TextSelectorConfig) -> None:
            self.config = config

    selector.TextSelector = TextSelector
    selector.TextSelectorConfig = TextSelectorConfig
    selector.TextSelectorType = TextSelectorType
    sys.modules["homeassistant.helpers.selector"] = selector
    helpers.selector = selector

    service_info = types.ModuleType("homeassistant.helpers.service_info")
    service_info.__path__ = []
    sys.modules["homeassistant.helpers.service_info"] = service_info

    hassio = types.ModuleType("homeassistant.helpers.service_info.hassio")
    hassio.HassioServiceInfo = object
    sys.modules["homeassistant.helpers.service_info.hassio"] = hassio

    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    class UpdateFailed(Exception):
        pass

    class DataUpdateCoordinator:
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, hass, **kwargs) -> None:
            self.hass = hass
            self.data = {}

        async def async_config_entry_first_refresh(self) -> None:
            self.data = await self._async_update_data()

        async def async_request_refresh(self) -> None:
            self.data = await self._async_update_data()

    class CoordinatorEntity:
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, coordinator) -> None:
            self.coordinator = coordinator

    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.UpdateFailed = UpdateFailed
    update_coordinator.CoordinatorEntity = CoordinatorEntity
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator

    device_registry = types.ModuleType("homeassistant.helpers.device_registry")

    class DeviceInfo(dict):
        pass

    device_registry.DeviceInfo = DeviceInfo
    sys.modules["homeassistant.helpers.device_registry"] = device_registry

    components = types.ModuleType("homeassistant.components")
    components.__path__ = []
    sys.modules["homeassistant.components"] = components

    button = types.ModuleType("homeassistant.components.button")

    class ButtonEntity:
        pass

    class ButtonEntityDescription:
        def __init__(self, **kwargs) -> None:
            self.__dict__.update(kwargs)

    button.ButtonEntity = ButtonEntity
    button.ButtonEntityDescription = ButtonEntityDescription
    sys.modules["homeassistant.components.button"] = button

    select = types.ModuleType("homeassistant.components.select")

    class SelectEntity:
        @property
        def options(self):
            return list(getattr(self, "_attr_options", []))

    select.SelectEntity = SelectEntity
    sys.modules["homeassistant.components.select"] = select


class GatewayIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_stubs()
        cls.package = load_module(
            "custom_components.ha_cellular_gateway",
            PACKAGE_PATH / "__init__.py",
            package=True,
        )
        cls.api = sys.modules["custom_components.ha_cellular_gateway.api"]
        cls.coordinator = sys.modules["custom_components.ha_cellular_gateway.coordinator"]
        cls.config_flow = load_module(
            "custom_components.ha_cellular_gateway.config_flow",
            PACKAGE_PATH / "config_flow.py",
        )
        cls.entity = load_module(
            "custom_components.ha_cellular_gateway.entity",
            PACKAGE_PATH / "entity.py",
        )
        cls.button = load_module(
            "custom_components.ha_cellular_gateway.button",
            PACKAGE_PATH / "button.py",
        )
        cls.select = load_module(
            "custom_components.ha_cellular_gateway.select",
            PACKAGE_PATH / "select.py",
        )
        cls.exceptions = sys.modules["homeassistant.exceptions"]
        cls.selector = sys.modules["homeassistant.helpers.selector"]
        cls.update_coordinator = sys.modules[
            "homeassistant.helpers.update_coordinator"
        ]

    def make_entry(
        self,
        *,
        url: str = "http://gateway.local:8099",
        token: str = "abc",
        entry_id: str = "entry-1",
        unique_id: str | None = None,
    ):
        return self.package.ConfigEntry(
            {"url": url, "token": token},
            entry_id=entry_id,
            unique_id=unique_id,
        )

    def make_flow(self, entry=None):
        flow = self.config_flow.GatewayConfigFlow()
        flow.hass = SimpleNamespace(
            config_entries=SimpleNamespace(async_get_entry=lambda entry_id: entry)
        )
        flow.context = {"entry_id": getattr(entry, "entry_id", "entry-1")}
        flow.async_abort = lambda **kwargs: kwargs
        flow.async_create_entry = lambda **kwargs: kwargs
        flow.async_show_form = lambda **kwargs: kwargs
        flow.async_set_unique_id = AsyncMock()
        flow.async_update_reload_and_abort = lambda existing, **kwargs: {
            "entry": existing,
            **kwargs,
        }
        flow._abort_if_unique_id_configured = lambda **kwargs: None
        flow._async_current_entries = lambda include_ignore=True: []
        return flow

    def test_manifest_does_not_use_single_config_entry_gate(self) -> None:
        manifest = json.loads((PACKAGE_PATH / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("single_config_entry", manifest)

    def test_manual_entry_deduplicates_normalized_url(self) -> None:
        flow = self.make_flow()
        entry = SimpleNamespace(data={"url": "http://gateway.local:8099"})
        flow._async_current_entries = lambda include_ignore=True: [entry]
        flow._validate = AsyncMock()

        result = asyncio.run(
            flow.async_step_user({"url": "http://gateway.local:8099/", "token": "abc"})
        )

        flow._validate.assert_awaited_once_with("http://gateway.local:8099", "abc")
        self.assertIs(result["entry"], entry)
        self.assertEqual(
            result["data_updates"],
            {"url": "http://gateway.local:8099", "token": "abc"},
        )

    def test_manual_entry_rejects_second_distinct_gateway(self) -> None:
        flow = self.make_flow()
        flow._async_current_entries = lambda include_ignore=True: [
            SimpleNamespace(data={"url": "http://gateway.local:8099"})
        ]
        flow._validate = AsyncMock()

        result = asyncio.run(
            flow.async_step_user({"url": "http://other-gateway.local:8099", "token": "abc"})
        )

        flow._validate.assert_awaited_once_with("http://other-gateway.local:8099", "abc")
        self.assertEqual(result, {"reason": "single_instance_allowed"})

    def test_manual_entry_uses_selectors(self) -> None:
        flow = self.make_flow()

        result = asyncio.run(flow.async_step_user())

        self.assertEqual(result["step_id"], "user")
        self.assertIsInstance(result["data_schema"]["url"], self.selector.TextSelector)
        self.assertEqual(result["data_schema"]["url"].config.type, "url")
        self.assertIsInstance(result["data_schema"]["token"], self.selector.TextSelector)
        self.assertEqual(result["data_schema"]["token"].config.type, "password")

    def test_manual_entry_surfaces_invalid_auth(self) -> None:
        flow = self.make_flow()
        flow._validate = AsyncMock(
            side_effect=self.api.GatewayApiAuthError("invalid token")
        )

        result = asyncio.run(
            flow.async_step_user({"url": "http://gateway.local:8099", "token": "abc"})
        )

        self.assertEqual(result["errors"], {"base": "invalid_auth"})

    def test_manual_entry_surfaces_unknown_api_error(self) -> None:
        flow = self.make_flow()
        flow._validate = AsyncMock(side_effect=self.api.GatewayApiError("boom"))

        result = asyncio.run(
            flow.async_step_user({"url": "http://gateway.local:8099", "token": "abc"})
        )

        self.assertEqual(result["errors"], {"base": "unknown"})

    def test_hassio_discovery_does_not_replace_manual_entry_on_validation_failure(
        self,
    ) -> None:
        flow = self.make_flow()
        entry = SimpleNamespace(data={"url": "http://gateway.local:8099"})
        flow._async_current_entries = lambda include_ignore=True: [entry]
        flow._validate = AsyncMock(
            side_effect=self.api.GatewayApiConnectionError("cannot_connect")
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

    def test_hassio_discovery_surfaces_invalid_auth(self) -> None:
        flow = self.make_flow()
        flow._validate = AsyncMock(
            side_effect=self.api.GatewayApiAuthError("bad token")
        )

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

        self.assertEqual(result, {"reason": "invalid_auth"})

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

    def test_hassio_discovery_rejects_second_distinct_gateway(self) -> None:
        flow = self.make_flow()
        flow._async_current_entries = lambda include_ignore=True: [
            SimpleNamespace(data={"url": "http://gateway.local:8099"})
        ]
        flow._validate = AsyncMock()

        result = asyncio.run(
            flow.async_step_hassio(
                SimpleNamespace(
                    config={
                        "host": "other-gateway.local",
                        "port": 8099,
                        "token": "fresh-token",
                    },
                    uuid="gateway-uuid",
                    name="Gateway",
                )
            )
        )

        flow._validate.assert_awaited_once_with(
            "http://other-gateway.local:8099",
            "fresh-token",
        )
        self.assertEqual(result, {"reason": "single_instance_allowed"})

    def test_reauth_updates_existing_entry(self) -> None:
        entry = self.make_entry(token="old-token")
        flow = self.make_flow(entry)
        flow._validate = AsyncMock()

        result = asyncio.run(flow.async_step_reauth_confirm({"token": "new-token"}))

        flow._validate.assert_awaited_once_with(
            "http://gateway.local:8099",
            "new-token",
        )
        self.assertIs(result["entry"], entry)
        self.assertEqual(result["data_updates"], {"token": "new-token"})
        self.assertEqual(result["reason"], "reauth_successful")

    def test_reauth_shows_invalid_auth_error(self) -> None:
        entry = self.make_entry()
        flow = self.make_flow(entry)
        flow._validate = AsyncMock(
            side_effect=self.api.GatewayApiAuthError("bad token")
        )

        result = asyncio.run(flow.async_step_reauth_confirm({"token": "new-token"}))

        self.assertEqual(result["step_id"], "reauth_confirm")
        self.assertEqual(result["errors"], {"base": "invalid_auth"})
        self.assertEqual(list(result["data_schema"]), ["token"])

    def test_reconfigure_updates_existing_entry(self) -> None:
        entry = self.make_entry(url="http://old-gateway.local:8099", token="old-token")
        flow = self.make_flow(entry)
        flow._async_current_entries = lambda include_ignore=True: [entry]
        flow._validate = AsyncMock()

        result = asyncio.run(
            flow.async_step_reconfigure(
                {"url": "http://new-gateway.local:8099/", "token": "new-token"}
            )
        )

        flow._validate.assert_awaited_once_with(
            "http://new-gateway.local:8099",
            "new-token",
        )
        self.assertIs(result["entry"], entry)
        self.assertEqual(
            result["data_updates"],
            {"url": "http://new-gateway.local:8099", "token": "new-token"},
        )
        self.assertEqual(result["reason"], "reconfigure_successful")

    def test_reconfigure_preserves_single_instance_behavior(self) -> None:
        entry = self.make_entry(entry_id="entry-1")
        other_entry = self.make_entry(
            url="http://other-gateway.local:8099",
            entry_id="entry-2",
        )
        flow = self.make_flow(entry)
        flow._async_current_entries = lambda include_ignore=True: [entry, other_entry]
        flow._validate = AsyncMock()

        result = asyncio.run(
            flow.async_step_reconfigure(
                {"url": "http://other-gateway.local:8099", "token": "abc"}
            )
        )

        self.assertEqual(result, {"reason": "single_instance_allowed"})

    def test_api_request_distinguishes_auth_connection_and_api_failures(self) -> None:
        client_error = self.api.aiohttp.ClientError

        class FakeResponse:
            def __init__(self, status: int, payload: dict) -> None:
                self.status = status
                self._payload = payload

            async def release(self):
                pass

            async def json(self):
                return self._payload

        class AuthSession:
            async def request(self, *args, **kwargs):
                return FakeResponse(401, {"error": "bad token"})

        class ApiSession:
            async def request(self, *args, **kwargs):
                return FakeResponse(500, {"error": "server exploded"})

        class ConnectionSession:
            async def request(self, *args, **kwargs):
                raise client_error("offline")

        class BodyReadErrorSession:
            async def request(self, *args, **kwargs):
                class DropResponse:
                    status = 200

                    async def release(self):
                        pass

                    async def json(self):
                        raise client_error("connection dropped during read")

                return DropResponse()

        class BodyReadTimeoutSession:
            async def request(self, *args, **kwargs):
                class SlowResponse:
                    status = 200

                    async def release(self):
                        pass

                    async def json(self):
                        raise TimeoutError("timed out reading body")

                return SlowResponse()

        api = self.api.GatewayApi(AuthSession(), "http://gateway.local:8099", "abc")
        with self.assertRaises(self.api.GatewayApiAuthError):
            asyncio.run(api.status())

        api = self.api.GatewayApi(ApiSession(), "http://gateway.local:8099", "abc")
        with self.assertRaises(self.api.GatewayApiError):
            asyncio.run(api.status())

        api = self.api.GatewayApi(
            ConnectionSession(),
            "http://gateway.local:8099",
            "abc",
        )
        with self.assertRaises(self.api.GatewayApiConnectionError):
            asyncio.run(api.status())

        api = self.api.GatewayApi(BodyReadErrorSession(), "http://gateway.local:8099", "abc")
        with self.assertRaises(self.api.GatewayApiConnectionError):
            asyncio.run(api.status())

        api = self.api.GatewayApi(BodyReadTimeoutSession(), "http://gateway.local:8099", "abc")
        with self.assertRaises(self.api.GatewayApiConnectionError):
            asyncio.run(api.status())

    def test_auth_rejection_with_non_json_body_raises_auth_error(self) -> None:
        class NonJsonAuthResponse:
            status = 401

            async def release(self):
                pass

            async def json(self):
                raise ValueError("not JSON")

        class NonJsonAuthSession:
            async def request(self, *args, **kwargs):
                return NonJsonAuthResponse()

        api = self.api.GatewayApi(NonJsonAuthSession(), "http://gateway.local:8099", "abc")
        with self.assertRaises(self.api.GatewayApiAuthError):
            asyncio.run(api.status())

    def test_coordinator_raises_auth_failed_for_invalid_auth(self) -> None:
        coordinator = self.coordinator.GatewayCoordinator(
            SimpleNamespace(),
            SimpleNamespace(
                status=AsyncMock(side_effect=self.api.GatewayApiAuthError("bad token"))
            ),
        )

        with self.assertRaises(self.exceptions.ConfigEntryAuthFailed):
            asyncio.run(coordinator._async_update_data())

    def test_coordinator_raises_update_failed_for_other_api_errors(self) -> None:
        coordinator = self.coordinator.GatewayCoordinator(
            SimpleNamespace(),
            SimpleNamespace(
                status=AsyncMock(
                    side_effect=self.api.GatewayApiConnectionError("offline")
                )
            ),
        )

        with self.assertRaises(self.update_coordinator.UpdateFailed):
            asyncio.run(coordinator._async_update_data())

    def test_setup_entry_propagates_auth_failures(self) -> None:
        original_coordinator = self.package.GatewayCoordinator
        auth_failed = self.exceptions.ConfigEntryAuthFailed

        class FailingCoordinator:
            def __init__(self, hass, api) -> None:
                self.api = api

            async def async_config_entry_first_refresh(self) -> None:
                raise auth_failed("bad token")

        try:
            self.package.GatewayCoordinator = FailingCoordinator
            hass = SimpleNamespace(
                config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock())
            )
            entry = self.make_entry()

            with self.assertRaises(self.exceptions.ConfigEntryAuthFailed):
                asyncio.run(self.package.async_setup_entry(hass, entry))
        finally:
            self.package.GatewayCoordinator = original_coordinator

    def test_button_press_raises_translated_auth_error(self) -> None:
        coordinator = SimpleNamespace(
            api=SimpleNamespace(
                reconcile=AsyncMock(
                    side_effect=self.api.GatewayApiAuthError("bad token")
                )
            ),
            async_request_refresh=AsyncMock(),
        )
        entity = self.button.GatewayButton(
            coordinator,
            "entry-1",
            self.button.DESCRIPTIONS[0],
        )

        with self.assertRaises(self.exceptions.HomeAssistantError) as ctx:
            asyncio.run(entity.async_press())

        self.assertEqual(ctx.exception.translation_domain, "ha_cellular_gateway")
        self.assertEqual(ctx.exception.translation_key, "invalid_auth")
        coordinator.async_request_refresh.assert_not_awaited()

    def test_mode_select_raises_translated_api_error(self) -> None:
        coordinator = SimpleNamespace(
            data={"mode": "active"},
            api=SimpleNamespace(
                set_mode=AsyncMock(
                    side_effect=self.api.GatewayApiError("mode change rejected")
                )
            ),
            async_request_refresh=AsyncMock(),
        )
        entity = self.select.GatewayModeSelect(coordinator, "entry-1")

        with self.assertRaises(self.exceptions.HomeAssistantError) as ctx:
            asyncio.run(entity.async_select_option("trial"))

        self.assertEqual(ctx.exception.translation_domain, "ha_cellular_gateway")
        self.assertEqual(ctx.exception.translation_key, "api_error")
        self.assertEqual(
            ctx.exception.translation_placeholders,
            {"error": "mode change rejected"},
        )
        coordinator.async_request_refresh.assert_not_awaited()

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

    def test_translations_cover_config_flow_descriptions_and_exceptions(self) -> None:
        translations = json.loads(
            (PACKAGE_PATH / "translations" / "en.json").read_text(encoding="utf-8")
        )

        self.assertIn("data_description", translations["config"]["step"]["user"])
        self.assertIn(
            "data_description",
            translations["config"]["step"]["reauth_confirm"],
        )
        self.assertIn("data_description", translations["config"]["step"]["reconfigure"])
        self.assertIn("invalid_auth", translations["config"]["error"])
        self.assertIn("unknown", translations["config"]["error"])
        self.assertIn("api_error", translations["exceptions"])


if __name__ == "__main__":
    unittest.main()
