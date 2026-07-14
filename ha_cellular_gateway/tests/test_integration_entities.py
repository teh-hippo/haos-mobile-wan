import asyncio
import importlib.util
import json
import sys
import types
import unittest
from dataclasses import dataclass
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
        "custom_components.ha_cellular_gateway.binary_sensor",
        "custom_components.ha_cellular_gateway.button",
        "custom_components.ha_cellular_gateway.config_flow",
        "custom_components.ha_cellular_gateway.const",
        "custom_components.ha_cellular_gateway.coordinator",
        "custom_components.ha_cellular_gateway.diagnostics",
        "custom_components.ha_cellular_gateway.entity",
        "custom_components.ha_cellular_gateway.select",
        "custom_components.ha_cellular_gateway.sensor",
        "homeassistant",
        "homeassistant.components",
        "homeassistant.components.binary_sensor",
        "homeassistant.components.button",
        "homeassistant.components.diagnostics",
        "homeassistant.components.select",
        "homeassistant.components.sensor",
        "homeassistant.config_entries",
        "homeassistant.const",
        "homeassistant.core",
        "homeassistant.helpers",
        "homeassistant.helpers.aiohttp_client",
        "homeassistant.helpers.device_registry",
        "homeassistant.helpers.entity",
        "homeassistant.helpers.entity_platform",
        "homeassistant.helpers.service_info",
        "homeassistant.helpers.service_info.hassio",
        "homeassistant.helpers.update_coordinator",
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

    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    sys.modules["homeassistant.core"] = core

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

    device_registry = types.ModuleType("homeassistant.helpers.device_registry")

    class DeviceInfo(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    device_registry.DeviceInfo = DeviceInfo
    sys.modules["homeassistant.helpers.device_registry"] = device_registry

    entity_helper = types.ModuleType("homeassistant.helpers.entity")

    class EntityCategory:
        CONFIG = "config"
        DIAGNOSTIC = "diagnostic"

    entity_helper.EntityCategory = EntityCategory
    sys.modules["homeassistant.helpers.entity"] = entity_helper

    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_platform.AddConfigEntryEntitiesCallback = object
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform

    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")

    class CoordinatorEntity:
        def __class_getitem__(cls, _item):
            return cls

        def __init__(self, coordinator) -> None:
            self.coordinator = coordinator

    update_coordinator.CoordinatorEntity = CoordinatorEntity
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator

    components = types.ModuleType("homeassistant.components")
    components.__path__ = []
    sys.modules["homeassistant.components"] = components

    @dataclass(frozen=True, kw_only=True)
    class EntityDescription:
        key: str
        name: str | None = None
        translation_key: str | None = None
        device_class: str | None = None
        entity_category: str | None = None
        entity_registry_enabled_default: bool = True
        icon: str | None = None
        options: list[str] | None = None

    binary_sensor = types.ModuleType("homeassistant.components.binary_sensor")

    @dataclass(frozen=True, kw_only=True)
    class BinarySensorEntityDescription(EntityDescription):
        pass

    class BinarySensorEntity:
        pass

    class BinarySensorDeviceClass:
        CONNECTIVITY = "connectivity"
        RUNNING = "running"

    binary_sensor.BinarySensorEntity = BinarySensorEntity
    binary_sensor.BinarySensorEntityDescription = BinarySensorEntityDescription
    binary_sensor.BinarySensorDeviceClass = BinarySensorDeviceClass
    sys.modules["homeassistant.components.binary_sensor"] = binary_sensor

    button = types.ModuleType("homeassistant.components.button")

    @dataclass(frozen=True, kw_only=True)
    class ButtonEntityDescription(EntityDescription):
        pass

    class ButtonEntity:
        pass

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

    sensor = types.ModuleType("homeassistant.components.sensor")

    @dataclass(frozen=True, kw_only=True)
    class SensorEntityDescription(EntityDescription):
        pass

    class SensorEntity:
        pass

    class SensorDeviceClass:
        ENUM = "enum"

    sensor.SensorEntity = SensorEntity
    sensor.SensorEntityDescription = SensorEntityDescription
    sensor.SensorDeviceClass = SensorDeviceClass
    sys.modules["homeassistant.components.sensor"] = sensor

    diagnostics = types.ModuleType("homeassistant.components.diagnostics")

    def async_redact_data(data, redact):
        return {
            key: ("**REDACTED**" if key in redact else value)
            for key, value in data.items()
        }

    diagnostics.async_redact_data = async_redact_data
    sys.modules["homeassistant.components.diagnostics"] = diagnostics

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

    coordinator = types.ModuleType("custom_components.ha_cellular_gateway.coordinator")
    coordinator.GatewayCoordinator = object
    sys.modules["custom_components.ha_cellular_gateway.coordinator"] = coordinator


class GatewayIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_stubs()
        cls.entity = load_module(
            "custom_components.ha_cellular_gateway.entity",
            PACKAGE_PATH / "entity.py",
        )
        cls.config_flow = load_module(
            "custom_components.ha_cellular_gateway.config_flow",
            PACKAGE_PATH / "config_flow.py",
        )
        cls.select = load_module(
            "custom_components.ha_cellular_gateway.select",
            PACKAGE_PATH / "select.py",
        )
        cls.button = load_module(
            "custom_components.ha_cellular_gateway.button",
            PACKAGE_PATH / "button.py",
        )
        cls.sensor = load_module(
            "custom_components.ha_cellular_gateway.sensor",
            PACKAGE_PATH / "sensor.py",
        )
        cls.binary_sensor = load_module(
            "custom_components.ha_cellular_gateway.binary_sensor",
            PACKAGE_PATH / "binary_sensor.py",
        )
        cls.diagnostics = load_module(
            "custom_components.ha_cellular_gateway.diagnostics",
            PACKAGE_PATH / "diagnostics.py",
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

    @staticmethod
    def make_status(**overrides: object) -> dict[str, object]:
        status = {
            "mode": "trial",
            "desired_mode": "trial",
            "upstream_mode": "iphone_usb",
            "upstream_pairing_state": "waiting_for_device",
            "downstream_interface": "eth1",
            "public_ip": "203.0.113.10",
            "last_error": None,
            "downstream_present": True,
            "rules_installed": False,
            "dnsmasq_running": True,
            "upstream_healthy": True,
            "rollback_armed": True,
            "safety_errors": [],
        }
        status.update(overrides)
        return status

    def test_manifest_does_not_use_single_config_entry_gate(self) -> None:
        manifest = json.loads((PACKAGE_PATH / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("single_config_entry", manifest)

    def test_translation_source_and_runtime_file_are_in_sync(self) -> None:
        strings = json.loads((PACKAGE_PATH / "strings.json").read_text(encoding="utf-8"))
        runtime = json.loads(
            (PACKAGE_PATH / "translations" / "en.json").read_text(encoding="utf-8")
        )

        self.assertEqual(strings, runtime)
        self.assertEqual(
            strings["config"]["abort"]["single_instance_allowed"],
            "Only one gateway can be configured",
        )

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

    def test_entity_metadata_uses_translations_and_expected_registry_flags(self) -> None:
        binary_descriptions = {
            description.key: description for description in self.binary_sensor.DESCRIPTIONS
        }
        sensor_descriptions = {
            description.key: description for description in self.sensor.DESCRIPTIONS
        }
        button_description = self.button.DESCRIPTIONS[0]

        self.assertIsNone(binary_descriptions["upstream_healthy"].name)
        self.assertEqual(
            binary_descriptions["upstream_healthy"].translation_key,
            "upstream_healthy",
        )
        self.assertEqual(
            binary_descriptions["upstream_healthy"].device_class,
            "connectivity",
        )
        self.assertFalse(binary_descriptions["rules_installed"].entity_registry_enabled_default)
        self.assertEqual(binary_descriptions["dnsmasq_running"].icon, "mdi:server-network")

        self.assertIsNone(sensor_descriptions["mode"].name)
        self.assertEqual(sensor_descriptions["mode"].translation_key, "mode")
        self.assertEqual(sensor_descriptions["mode"].device_class, "enum")
        self.assertEqual(sensor_descriptions["mode"].options, ["disabled", "trial", "active"])
        self.assertFalse(sensor_descriptions["public_ip"].entity_registry_enabled_default)
        self.assertEqual(sensor_descriptions["upstream_pairing_state"].icon, "mdi:usb-port")

        self.assertIsNone(button_description.name)
        self.assertEqual(button_description.translation_key, "reconcile")
        self.assertFalse(button_description.entity_registry_enabled_default)
        self.assertEqual(self.select.GatewayModeSelect._attr_translation_key, "mode_control")
        self.assertEqual(self.select.GatewayModeSelect._attr_entity_category, "config")

    def test_mode_select_only_exposes_supported_actions(self) -> None:
        coordinator = SimpleNamespace(
            data=self.make_status(mode="active"),
            api=SimpleNamespace(set_mode=AsyncMock()),
            async_request_refresh=AsyncMock(),
        )
        entity = self.select.GatewayModeSelect(coordinator, "entry-1")

        self.assertEqual(entity._attr_unique_id, "entry-1_mode_control")
        self.assertEqual(entity.options, ["disabled", "trial"])
        self.assertIsNone(entity.current_option)

        asyncio.run(entity.async_select_option("trial"))

        coordinator.api.set_mode.assert_awaited_once_with("trial")
        coordinator.async_request_refresh.assert_awaited_once()

    def test_safety_sensor_preserves_state_semantics_and_attributes(self) -> None:
        healthy = self.binary_sensor.GatewaySafetySensor(
            SimpleNamespace(data=self.make_status()),
            "entry-1",
        )
        failing = self.binary_sensor.GatewaySafetySensor(
            SimpleNamespace(data=self.make_status(safety_errors=["missing route"])),
            "entry-1",
        )

        self.assertEqual(healthy._attr_unique_id, "entry-1_safety_checks")
        self.assertTrue(healthy.is_on)
        self.assertEqual(healthy.icon, "mdi:shield-check")
        self.assertEqual(healthy.extra_state_attributes, {"errors": []})

        self.assertFalse(failing.is_on)
        self.assertEqual(failing.icon, "mdi:shield-alert")
        self.assertEqual(failing.extra_state_attributes, {"errors": ["missing route"]})

    def test_button_and_sensor_unique_ids_are_preserved(self) -> None:
        coordinator = SimpleNamespace(
            data=self.make_status(),
            api=SimpleNamespace(reconcile=AsyncMock()),
            async_request_refresh=AsyncMock(),
        )

        button = self.button.GatewayButton(
            coordinator,
            "entry-1",
            self.button.DESCRIPTIONS[0],
        )
        sensor = self.sensor.GatewaySensor(
            coordinator,
            "entry-1",
            self.sensor.DESCRIPTIONS[0],
        )

        self.assertEqual(button._attr_unique_id, "entry-1_reconcile")
        self.assertEqual(sensor._attr_unique_id, "entry-1_mode")
        self.assertEqual(sensor.native_value, "trial")

        asyncio.run(button.async_press())

        coordinator.api.reconcile.assert_awaited_once()
        coordinator.async_request_refresh.assert_awaited_once()

    def test_diagnostics_redact_runtime_data(self) -> None:
        entry = SimpleNamespace(
            data={"url": "http://gateway.local:8099", "token": "secret"},
            runtime_data=SimpleNamespace(
                data={"public_ip": "203.0.113.10", "last_error": "boom", "mode": "trial"}
            ),
        )

        result = asyncio.run(
            self.diagnostics.async_get_config_entry_diagnostics(object(), entry)
        )

        self.assertEqual(result["entry"]["url"], "**REDACTED**")
        self.assertEqual(result["entry"]["token"], "**REDACTED**")
        self.assertEqual(result["status"]["public_ip"], "**REDACTED**")
        self.assertEqual(result["status"]["last_error"], "**REDACTED**")
        self.assertEqual(result["status"]["mode"], "trial")


if __name__ == "__main__":
    unittest.main()
