from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)

UrlOpen = Callable[..., object]

MQTT_SERVICE_URL = "http://supervisor/services/mqtt"


@dataclass(frozen=True)
class MqttCredentials:
    host: str
    port: int
    username: str | None
    password: str | None
    ssl: bool


def read_mqtt_service(
    *,
    token: str | None = None,
    urlopen: UrlOpen | None = None,
) -> MqttCredentials | None:
    supervisor_token = (
        token if token is not None else os.environ.get("SUPERVISOR_TOKEN")
    )
    if not supervisor_token:
        _LOGGER.warning("MQTT is unavailable: Supervisor token is missing")
        return None
    request = urllib.request.Request(
        MQTT_SERVICE_URL,
        method="GET",
        headers={"Authorization": f"******"},
    )
    opener = urlopen or urllib.request.urlopen
    try:
        raw = opener(request, timeout=10).read()
        payload = json.loads(raw.decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as err:
        _LOGGER.warning("MQTT service lookup failed: %s", err)
        return None
    return _parse(payload)


def _parse(payload: object) -> MqttCredentials | None:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        _LOGGER.warning("MQTT service response is missing broker details")
        return None
    host = data.get("host")
    if not isinstance(host, str) or not host:
        _LOGGER.warning("MQTT service response is missing a broker host")
        return None
    try:
        port = int(data["port"])
    except (KeyError, TypeError, ValueError):
        _LOGGER.warning("MQTT service response has an invalid broker port")
        return None
    return MqttCredentials(
        host=host,
        port=port,
        username=_optional_str(data.get("username")),
        password=_optional_str(data.get("password")),
        ssl=bool(data.get("ssl")),
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
