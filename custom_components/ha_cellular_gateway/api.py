from __future__ import annotations

import asyncio
from typing import Any, cast

import aiohttp

from .models import GatewaySelectableMode, GatewayStatus


class GatewayApiError(RuntimeError):
    pass


class GatewayApi:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        token: str,
    ) -> None:
        self._session = session
        self._url = url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        try:
            async with asyncio.timeout(10):
                response = await self._session.request(
                    method,
                    f"{self._url}{path}",
                    headers=self._headers,
                    json=payload,
                )
                data = await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise GatewayApiError("Unable to communicate with gateway app") from err
        if not isinstance(data, dict):
            raise GatewayApiError("Gateway app returned an invalid response")
        if response.status >= 400:
            raise GatewayApiError(str(data.get("error", f"HTTP {response.status}")))
        return cast(dict[str, object], data)

    async def status(self) -> GatewayStatus:
        return cast(GatewayStatus, await self._request("GET", "/v1/status"))

    async def reconcile(self) -> dict[str, object]:
        return await self._request("POST", "/v1/reconcile")

    async def set_mode(self, mode: GatewaySelectableMode) -> dict[str, object]:
        return await self._request("POST", "/v1/mode", {"mode": mode})
