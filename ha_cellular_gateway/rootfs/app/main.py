from __future__ import annotations

import signal
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api_server import GatewayServer
from app.command import CommandRunner
from app.config import GatewayConfig
from app.discovery import publish_discovery
from app.gateway import GatewayEngine, load_or_create_token
from app.hotspot import provision_hotspot


def main() -> None:
    runner = CommandRunner()
    config, config_error = GatewayConfig.load_path(
        run=lambda *args, **kwargs: runner.run(
            list(args),
            check=kwargs.get("check", True),
            timeout=kwargs.get("timeout", 20),
        )
    )
    hotspot_error = provision_hotspot(config)
    startup_error = "; ".join(
        error for error in (config_error, hotspot_error) if error
    ) or None
    engine = GatewayEngine(config, runner=runner, config_error=startup_error)
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
