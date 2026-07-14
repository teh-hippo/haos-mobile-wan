from __future__ import annotations

from unittest.mock import AsyncMock

import aiohttp
import pytest

from custom_components.ha_cellular_gateway.api import GatewayApi, GatewayApiError


@pytest.mark.parametrize(
    ("method_name", "expected_method", "expected_path", "expected_payload"),
    [
        ("status", "GET", "/v1/status", None),
        ("reconcile", "POST", "/v1/reconcile", None),
        ("set_mode", "POST", "/v1/mode", {"mode": "trial"}),
    ],
)
async def test_gateway_api_requests(
    method_name: str,
    expected_method: str,
    expected_path: str,
    expected_payload: dict[str, str] | None,
) -> None:
    response = AsyncMock(status=200)
    response.json = AsyncMock(return_value={"ok": True})
    session = AsyncMock()
    session.request.return_value = response
    api = GatewayApi(session, "http://gateway.local:8099/", "secret")

    result = await getattr(api, method_name)(
        *(["trial"] if method_name == "set_mode" else [])
    )

    assert result == {"ok": True}
    session.request.assert_awaited_once_with(
        expected_method,
        f"http://gateway.local:8099{expected_path}",
        headers={"Authorization": 'Bearer secret'},
        json=expected_payload,
    )


async def test_gateway_api_raises_error_for_http_failure() -> None:
    response = AsyncMock(status=500)
    response.json = AsyncMock(return_value={"error": "boom"})
    session = AsyncMock()
    session.request.return_value = response
    api = GatewayApi(session, "http://gateway.local:8099", "secret")

    with pytest.raises(GatewayApiError, match="boom"):
        await api.status()


@pytest.mark.parametrize(
    "side_effect",
    [aiohttp.ClientError("offline"), TimeoutError(), ValueError("bad json")],
)
async def test_gateway_api_wraps_transport_errors(side_effect: Exception) -> None:
    session = AsyncMock()
    if isinstance(side_effect, ValueError):
        response = AsyncMock(status=200)
        response.json = AsyncMock(side_effect=side_effect)
        session.request.return_value = response
    else:
        session.request.side_effect = side_effect
    api = GatewayApi(session, "http://gateway.local:8099", "secret")

    with pytest.raises(
        GatewayApiError,
        match="Unable to communicate with gateway app",
    ):
        await api.status()
