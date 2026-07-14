import asyncio
import importlib.util
import sys
import types
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace


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
        "custom_components.ha_cellular_gateway.const",
        "homeassistant",
        "homeassistant.components",
        "homeassistant.components.diagnostics",
        "homeassistant.const",
        "homeassistant.helpers",
        "homeassistant.helpers.issue_registry",
    ):
        sys.modules.pop(name, None)

    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = [str(REPO_ROOT / "custom_components")]
    sys.modules["custom_components"] = custom_components

    package = types.ModuleType("custom_components.ha_cellular_gateway")
    package.__path__ = [str(PACKAGE_PATH)]
    package.GatewayConfigEntry = object
    sys.modules["custom_components.ha_cellular_gateway"] = package

    homeassistant = types.ModuleType("homeassistant")
    sys.modules["homeassistant"] = homeassistant

    components = types.ModuleType("homeassistant.components")
    components.__path__ = []
    sys.modules["homeassistant.components"] = components

    diagnostics = types.ModuleType("homeassistant.components.diagnostics")

    def async_redact_data(data, keys):
        if isinstance(data, dict):
            return {
                key: ("**REDACTED**" if key in keys else async_redact_data(value, keys))
                for key, value in data.items()
            }
        if isinstance(data, list):
            return [async_redact_data(value, keys) for value in data]
        return data

    diagnostics.async_redact_data = async_redact_data
    sys.modules["homeassistant.components.diagnostics"] = diagnostics

    const = types.ModuleType("homeassistant.const")
    const.CONF_URL = "url"
    sys.modules["homeassistant.const"] = const

    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    sys.modules["homeassistant.helpers"] = helpers

    issue_registry = types.ModuleType("homeassistant.helpers.issue_registry")
    issue_registry.created = []
    issue_registry.deleted = []
    issue_registry.IssueSeverity = SimpleNamespace(ERROR="error")

    def async_create_issue(hass, domain, issue_id, **kwargs):
        issue_registry.created.append((hass, domain, issue_id, kwargs))

    def async_delete_issue(hass, domain, issue_id):
        issue_registry.deleted.append((hass, domain, issue_id))

    issue_registry.async_create_issue = async_create_issue
    issue_registry.async_delete_issue = async_delete_issue
    sys.modules["homeassistant.helpers.issue_registry"] = issue_registry

    gateway_const = types.ModuleType("custom_components.ha_cellular_gateway.const")
    gateway_const.CONF_TOKEN = "token"
    gateway_const.DOMAIN = "ha_cellular_gateway"
    sys.modules["custom_components.ha_cellular_gateway.const"] = gateway_const


class GatewayRepairsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_stubs()
        cls.repairs = load_module(
            "custom_components.ha_cellular_gateway.repairs",
            PACKAGE_PATH / "repairs.py",
        )
        cls.diagnostics = load_module(
            "custom_components.ha_cellular_gateway.diagnostics",
            PACKAGE_PATH / "diagnostics.py",
        )
        cls.issue_registry = sys.modules["homeassistant.helpers.issue_registry"]

    def setUp(self) -> None:
        self.issue_registry.created.clear()
        self.issue_registry.deleted.clear()

    def test_sync_repairs_creates_and_clears_stable_issue(self) -> None:
        current = self.repairs.sync_repairs(
            "hass",
            "entry-1",
            "Gateway",
            set(),
            {
                "issues": [
                    {
                        "id": "downstream_missing",
                        "translation_key": "downstream_configuration",
                        "repairable": True,
                        "transient": False,
                    }
                ]
            },
        )

        self.assertEqual(current, {"downstream_configuration"})
        self.assertEqual(
            self.issue_registry.created,
            [
                (
                    "hass",
                    "ha_cellular_gateway",
                    "entry-1_downstream_configuration",
                    {
                        "is_fixable": False,
                        "issue_domain": "ha_cellular_gateway",
                        "severity": "error",
                        "translation_key": "downstream_configuration",
                        "translation_placeholders": {"entry_title": "Gateway"},
                    },
                )
            ],
        )

        current = self.repairs.sync_repairs(
            "hass",
            "entry-1",
            "Gateway",
            current,
            {"issues": []},
        )

        self.assertEqual(current, set())
        self.assertEqual(
            self.issue_registry.deleted,
            [
                (
                    "hass",
                    "ha_cellular_gateway",
                    "entry-1_downstream_configuration",
                )
            ],
        )

    def test_sync_repairs_ignores_transient_connectivity_issue(self) -> None:
        current = self.repairs.sync_repairs(
            "hass",
            "entry-1",
            "Gateway",
            set(),
            {
                "issues": [
                    {
                        "id": "upstream_waiting_for_device",
                        "translation_key": None,
                        "repairable": False,
                        "transient": True,
                    }
                ]
            },
        )

        self.assertEqual(current, set())
        self.assertEqual(self.issue_registry.created, [])

    def test_diagnostics_redacts_raw_sensitive_fields_but_keeps_structured_issues(self) -> None:
        entry = SimpleNamespace(
            data={"url": "http://gateway.local:8099", "token": "secret"},
            runtime_data=SimpleNamespace(
                data={
                    "last_error": "Unexpected main-table default route: usb0",
                    "safety_errors": ["Strict rp_filter is enabled on usb0"],
                    "upstream_runtime_interface": "usb0",
                    "upstream_pairing_message": "iPhone is paired but the host ipheth driver is not active",
                    "upstream_device_udid": "00008110",
                    "issues": [
                        {
                            "id": "strict_rp_filter_enabled",
                            "translation_key": "host_configuration",
                            "repairable": True,
                            "transient": False,
                            "message": "Strict rp_filter is enabled on a required interface",
                        }
                    ],
                }
            ),
        )

        result = asyncio.run(
            self.diagnostics.async_get_config_entry_diagnostics(None, deepcopy(entry))
        )

        self.assertEqual(result["entry"]["url"], "**REDACTED**")
        self.assertEqual(result["entry"]["token"], "**REDACTED**")
        self.assertEqual(result["status"]["last_error"], "**REDACTED**")
        self.assertEqual(result["status"]["safety_errors"], "**REDACTED**")
        self.assertEqual(result["status"]["upstream_runtime_interface"], "**REDACTED**")
        self.assertEqual(result["status"]["upstream_pairing_message"], "**REDACTED**")
        self.assertEqual(result["status"]["upstream_device_udid"], "**REDACTED**")
        self.assertEqual(
            result["status"]["issues"],
            [
                {
                    "id": "strict_rp_filter_enabled",
                    "translation_key": "host_configuration",
                    "repairable": True,
                    "transient": False,
                    "message": "Strict rp_filter is enabled on a required interface",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
