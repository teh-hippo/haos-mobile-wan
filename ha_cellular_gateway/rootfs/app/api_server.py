from __future__ import annotations

import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .gateway import GatewayEngine

_LOGGER = logging.getLogger(__name__)


class GatewayHandler(BaseHTTPRequestHandler):
    server: "GatewayServer"

    def log_request(
        self,
        code: int | str = "-",
        size: int | str = "-",
    ) -> None:
        try:
            status = int(code)
        except (TypeError, ValueError):
            status = 0
        level = logging.WARNING if status >= 400 else logging.DEBUG
        _LOGGER.log(level, '"%s" %s %s', self.requestline, code, size)

    def log_error(self, format: str, *args: object) -> None:
        _LOGGER.warning(format, *args)

    def log_message(self, format: str, *args: object) -> None:
        _LOGGER.debug(format, *args)

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        expected = f"Bearer {self.server.api_token}"
        return self.headers.get("Authorization") == expected

    def do_GET(self) -> None:
        if self.path == "/health":
            health = self.server.engine.health()
            code = HTTPStatus.OK if health["ok"] else HTTPStatus.SERVICE_UNAVAILABLE
            self._json(code, health)
            return
        if self.path == "/v2/status":
            if not self._authorized():
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            self._json(HTTPStatus.OK, self.server.engine.status())
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        engine: GatewayEngine,
        api_token: str,
    ) -> None:
        super().__init__(address, GatewayHandler)
        self.engine = engine
        self.api_token = api_token
