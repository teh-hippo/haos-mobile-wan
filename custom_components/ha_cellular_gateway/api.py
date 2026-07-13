from __future__ import annotations

import asyncio
from typing import Any

import aiohttp


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
    ) -> dict[str, Any]:
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
        if response.status >= 400:
            raise GatewayApiError(str(data.get("error", f"HTTP {response.status}")))
        return data

    async def status(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/status")

    async def reconcile(self) -> dict[str, Any]:
        return await self._request("POST", "/v1/reconcile")

    async def seek(self) -> dict[str, Any]:
        return await self._request("POST", "/v1/seek")

    async def set_mode(self, mode: str) -> dict[str, Any]:
        return await self._request("POST", "/v1/mode", {"mode": mode})
