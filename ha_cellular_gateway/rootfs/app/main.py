from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api_server import GatewayServer
from app.api_token import load_or_create_token
from app.command import CommandRunner
from app.config import GatewayConfig
from app.gateway import GatewayEngine
from app.mqtt_publisher import MqttPublisher
from app.options_migration import prune_legacy_options

_LOGGER = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(levelname)s %(name)s: %(message)s",
    )


def main() -> None:
    configure_logging()
    runner = CommandRunner()
    migration_error = prune_legacy_options()
    if migration_error:
        _LOGGER.warning("%s", migration_error)
    config, config_error = GatewayConfig.load_path()
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
    publisher = MqttPublisher(engine)
    publisher.start()

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
        publisher.stop()
        engine.stop()
        server.server_close()
        worker.join(timeout=10)


if __name__ == "__main__":
    main()
