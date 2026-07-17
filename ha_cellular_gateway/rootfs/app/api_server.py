from __future__ import annotations

import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .errors import GatewayError
from .gateway import GatewayEngine

_LOGGER = logging.getLogger(__name__)


class GatewayHandler(BaseHTTPRequestHandler):
    server: "GatewayServer"

    def log_message(self, format: str, *args: object) -> None:
        _LOGGER.debug("%s", format % args)

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

    def _body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("request body must be an object")
        return data

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
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        try:
            if self.path == "/v2/reconcile":
                self.server.engine.reconcile()
                self._json(HTTPStatus.OK, self.server.engine.status())
                return
            if self.path == "/v2/enabled":
                self._set_enabled()
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except (GatewayError, OSError, ValueError) as err:
            self._json(HTTPStatus.CONFLICT, {"error": str(err)})

    def _set_enabled(self) -> None:
        enabled = self._body().get("enabled")
        if not isinstance(enabled, bool):
            raise GatewayError("Enabled must be true or false")
        if not enabled:
            self.server.engine.cleanup(preserve_host_protection=True)
        else:
            self.server.engine.apply()
        self._json(HTTPStatus.OK, self.server.engine.status())


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
