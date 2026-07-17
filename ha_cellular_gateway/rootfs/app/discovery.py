from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from .config import GatewayConfig

_LOGGER = logging.getLogger(__name__)


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
        _LOGGER.warning("Discovery publish failed: %s", err)
