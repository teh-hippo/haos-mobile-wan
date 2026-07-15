from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .errors import GatewayError
from .gateway import GatewayEngine


class GatewayHandler(BaseHTTPRequestHandler):
    server: "GatewayServer"

    def log_message(self, format: str, *args: object) -> None:
        print(f"api: {format % args}", flush=True)

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
        if self.path == "/v1/status":
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
            if self.path == "/v1/reconcile":
                self.server.engine.reconcile()
                self._json(HTTPStatus.OK, self.server.engine.status())
                return
            if self.path == "/v1/mode":
                self._set_mode()
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except (GatewayError, OSError, ValueError) as err:
            self._json(HTTPStatus.CONFLICT, {"error": str(err)})

    def _set_mode(self) -> None:
        mode = str(self._body().get("mode", ""))
        if mode not in {"disabled", "active"}:
            raise GatewayError("Mode must be disabled or active")
        if mode == "disabled":
            self.server.engine.cleanup(preserve_host_protection=True)
        else:
            self.server.engine.apply(mode)
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
