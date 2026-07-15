from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from homeassistant.const import CONF_URL
from pytest_homeassistant_custom_component.common import MockConfigEntry

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.ha_cellular_gateway.const import CONF_TOKEN, DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def status_payload() -> dict[str, object]:
    return {
        "enabled": True,
        "configured_enabled": False,
        "active": True,
        "mobile_connection": "iphone_usb_wifi_fallback",
        "active_connection": "iphone_usb",
        "fallback_active": False,
        "fallback_reason": None,
        "connection_warnings": [],
        "upstream_pairing_state": "paired",
        "downstream_interface": "eth1",
        "public_ip": "203.0.113.10",
        "last_error": "none",
        "upstream_healthy": True,
        "downstream_present": True,
        "rules_installed": True,
        "dnsmasq_running": True,
        "safety_errors": [],
    }


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="HAOS Mobile WAN",
        unique_id="gateway-uuid",
        data={CONF_URL: "http://gateway.local:8099", CONF_TOKEN: "token"},
    )


@pytest.fixture
def runtime_coordinator(status_payload: dict[str, object]):
    return type(
        "RuntimeCoordinator",
        (),
        {
            "data": dict(status_payload),
            "api": type(
                "RuntimeApi",
                (),
                {
                    "reconcile": AsyncMock(return_value={}),
                    "set_enabled": AsyncMock(return_value={}),
                },
            )(),
            "async_request_refresh": AsyncMock(),
        },
    )()
