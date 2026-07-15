from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components.ha_cellular_gateway.diagnostics import (
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_redacts_sensitive_values(
    hass,
    mock_config_entry,
    status_payload: dict[str, object],
) -> None:
    mock_config_entry.runtime_data = type(
        "RuntimeCoordinator",
        (),
        {
            "data": {
                **status_payload,
                "public_ip": "203.0.113.10",
                "downstream_interface": "eth1",
                "management_address": "192.168.1.2",
                "last_error": "Strict rp_filter is enabled on usb0",
                "safety_errors": ["Strict rp_filter is enabled on usb0"],
                "fallback_reason": "USB interface usb0 is unavailable",
                "connection_warnings": ["Wi-Fi interface wlan0 is unavailable"],
                "upstream_runtime_interface": "usb0",
                "upstream_pairing_message": "ipheth driver is not active",
                "upstream_lockdown_path": "/var/run/usbmuxd",
                "hotspot_ssid": "Phone",
                "hotspot_password": "supersecret",
            },
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

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert result["entry"]["token"] == "**REDACTED**"
    assert result["entry"]["url"] == "**REDACTED**"
    assert result["status"]["public_ip"] == "**REDACTED**"
    assert result["status"]["downstream_interface"] == "**REDACTED**"
    assert result["status"]["management_address"] == "**REDACTED**"
    assert result["status"]["last_error"] == "**REDACTED**"
    assert result["status"]["safety_errors"] == "**REDACTED**"
    assert result["status"]["fallback_reason"] == "**REDACTED**"
    assert result["status"]["connection_warnings"] == "**REDACTED**"
    assert result["status"]["upstream_runtime_interface"] == "**REDACTED**"
    assert result["status"]["upstream_pairing_message"] == "**REDACTED**"
    assert result["status"]["upstream_lockdown_path"] == "**REDACTED**"
    assert result["status"]["hotspot_ssid"] == "**REDACTED**"
    assert result["status"]["hotspot_password"] == "**REDACTED**"


async def test_diagnostics_preserves_structured_issues(
    hass,
    mock_config_entry,
    status_payload: dict[str, object],
) -> None:
    issues = [
        {
            "id": "strict_rp_filter_enabled",
            "translation_key": "host_configuration",
            "repairable": True,
            "transient": False,
            "message": "Strict rp_filter is enabled on a required interface",
        }
    ]
    mock_config_entry.runtime_data = type(
        "RuntimeCoordinator",
        (),
        {
            "data": {**status_payload, "issues": issues},
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

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert result["status"]["issues"] == issues
