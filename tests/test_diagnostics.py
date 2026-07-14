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
            },
            "api": type(
                "RuntimeApi",
                (),
                {
                    "reconcile": AsyncMock(return_value={}),
                    "set_mode": AsyncMock(return_value={}),
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
