#!/usr/bin/python3
from __future__ import annotations

import json
import os
import signal
import sys
import threading
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.command import CommandRunner
from app.config import GatewayConfig
from app.errors import GatewayError
from app.gateway import GatewayEngine, load_or_create_token


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
        return json.loads(self.rfile.read(length))

    def do_GET(self) -> None:
        if self.path == "/health":
            health = self.server.engine.health()
            code = (
                HTTPStatus.OK
                if health["ok"]
                else HTTPStatus.SERVICE_UNAVAILABLE
            )
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
                mode = str(self._body().get("mode", ""))
                if mode == "disabled":
                    self.server.engine.cleanup(
                        preserve_host_protection=True,
                    )
                else:
                    self.server.engine.apply(mode)
                self._json(HTTPStatus.OK, self.server.engine.status())
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except (GatewayError, OSError, ValueError) as err:
            self._json(HTTPStatus.CONFLICT, {"error": str(err)})


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


def publish_discovery(config: GatewayConfig, token: str) -> None:
    supervisor_token = os.environ.get("SUPERVISOR_TOKEN")
    if not supervisor_token:
        return
    payload = json.dumps(
        {
            "service": "ha_cellular_gateway",
            "config": {
                "host": config.api_bind,
                "port": config.api_port,
                "token": token,
            },
        }
    ).encode()
    request = urllib.request.Request(
        "http://supervisor/discovery",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {supervisor_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        urllib.request.urlopen(request, timeout=10).read()
    except (OSError, urllib.error.URLError) as err:
        print(f"discovery: {err}", flush=True)


def main() -> None:
    runner = CommandRunner()
    config, config_error = GatewayConfig.load_path(
        run=lambda *args, **kwargs: runner.run(
            list(args),
            check=kwargs.get("check", True),
            timeout=kwargs.get("timeout", 20),
        )
    )
    engine = GatewayEngine(
        config,
        runner=runner,
        config_error=config_error,
    )
    token = load_or_create_token()
    server = GatewayServer((config.api_bind, config.api_port), engine, token)
    worker = threading.Thread(
        target=engine.run_loop,
        name="gateway-reconcile",
        daemon=True,
    )
    worker.start()
    publish_discovery(config, token)

    def stop(*_: object) -> None:
        threading.Thread(
            target=server.shutdown,
            name="gateway-api-shutdown",
            daemon=True,
        ).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        engine.stop()
        server.server_close()
        worker.join(timeout=10)


if __name__ == "__main__":
    main()
