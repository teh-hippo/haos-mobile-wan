from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest

from custom_components.ha_cellular_gateway.api import (
    GatewayApi,
    GatewayApiAuthError,
    GatewayApiConnectionError,
    GatewayApiError,
)


@pytest.mark.parametrize(
    ("method_name", "expected_method", "expected_path", "expected_payload"),
    [
        ("status", "GET", "/v2/status", None),
        ("reconcile", "POST", "/v2/reconcile", None),
        ("set_enabled", "POST", "/v2/enabled", {"enabled": True}),
    ],
)
async def test_gateway_api_requests(
    method_name: str,
    expected_method: str,
    expected_path: str,
    expected_payload: dict[str, object] | None,
) -> None:
    response = AsyncMock(status=200)
    response.json = AsyncMock(return_value={"ok": True})
    session = AsyncMock()
    session.request.return_value = response
    api = GatewayApi(session, "http://gateway.local:8099/", "secret")

    result = await getattr(api, method_name)(
        *([True] if method_name == "set_enabled" else [])
    )

    assert result == {"ok": True}
    session.request.assert_awaited_once_with(
        expected_method,
        f"http://gateway.local:8099{expected_path}",
        headers={"Authorization": 'Bearer secret'},
        json=expected_payload,
    )


async def test_gateway_api_raises_error_for_non_dict_response() -> None:
    response = AsyncMock(status=200)
    response.json = AsyncMock(return_value=["not", "a", "dict"])
    session = AsyncMock()
    session.request.return_value = response
    api = GatewayApi(session, "http://gateway.local:8099", "secret")

    with pytest.raises(GatewayApiError, match="invalid response"):
        await api.status()


async def test_gateway_api_raises_error_for_http_failure() -> None:
    response = AsyncMock(status=500)
    response.json = AsyncMock(return_value={"error": "boom"})
    session = AsyncMock()
    session.request.return_value = response
    api = GatewayApi(session, "http://gateway.local:8099", "secret")

    with pytest.raises(GatewayApiError, match="boom"):
        await api.status()


@pytest.mark.parametrize("status", [401, 403])
async def test_gateway_api_raises_auth_error_for_auth_status(status: int) -> None:
    response = Mock(status=status)
    response.release = Mock()
    response.json = AsyncMock()
    session = AsyncMock()
    session.request.return_value = response
    api = GatewayApi(session, "http://gateway.local:8099", "secret")

    with pytest.raises(GatewayApiAuthError):
        await api.status()

    response.release.assert_called_once_with()
    response.json.assert_not_awaited()


async def test_gateway_api_raises_auth_error_for_non_json_401() -> None:
    response = Mock(status=401)
    response.release = Mock()
    response.json = AsyncMock(side_effect=ValueError("not JSON"))
    session = AsyncMock()
    session.request.return_value = response
    api = GatewayApi(session, "http://gateway.local:8099", "secret")

    with pytest.raises(GatewayApiAuthError):
        await api.status()

    response.release.assert_called_once_with()


@pytest.mark.parametrize(
    "side_effect",
    [aiohttp.ClientError("offline"), TimeoutError()],
)
async def test_gateway_api_raises_connection_error_for_transport_failure(
    side_effect: Exception,
) -> None:
    session = AsyncMock()
    session.request.side_effect = side_effect
    api = GatewayApi(session, "http://gateway.local:8099", "secret")

    with pytest.raises(GatewayApiConnectionError, match="Unable to communicate with gateway app"):
        await api.status()


@pytest.mark.parametrize(
    "side_effect",
    [aiohttp.ClientError("connection dropped"), TimeoutError("timed out reading")],
)
async def test_gateway_api_raises_connection_error_for_body_read_failure(
    side_effect: Exception,
) -> None:
    response = AsyncMock(status=200)
    response.json = AsyncMock(side_effect=side_effect)
    session = AsyncMock()
    session.request.return_value = response
    api = GatewayApi(session, "http://gateway.local:8099", "secret")

    with pytest.raises(GatewayApiConnectionError, match="Unable to communicate with gateway app"):
        await api.status()


async def test_gateway_api_raises_error_for_invalid_json_response() -> None:
    response = AsyncMock(status=200)
    response.json = AsyncMock(side_effect=ValueError("bad json"))
    session = AsyncMock()
    session.request.return_value = response
    api = GatewayApi(session, "http://gateway.local:8099", "secret")

    with pytest.raises(GatewayApiError, match="Invalid response from gateway app"):
        await api.status()
