from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

_LOGGER = logging.getLogger(__name__)


class ReadResponse(Protocol):
    def read(self) -> bytes: ...


UrlOpen = Callable[..., ReadResponse]

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
    warn: bool = True,
) -> MqttCredentials | None:
    supervisor_token = (
        token if token is not None else os.environ.get("SUPERVISOR_TOKEN")
    )
    if not supervisor_token:
        _log_failure(warn, "MQTT is unavailable: Supervisor token is missing")
        return None
    request = urllib.request.Request(
        MQTT_SERVICE_URL,
        method="GET",
        headers={"Authorization": f"Bearer {supervisor_token}"},
    )
    opener = urlopen or urllib.request.urlopen
    try:
        raw = opener(request, timeout=10).read()
        payload = json.loads(raw.decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as err:
        _log_failure(warn, "MQTT service lookup failed: %s", err)
        return None
    return _parse(payload, warn=warn)


def _parse(payload: object, *, warn: bool) -> MqttCredentials | None:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        _log_failure(warn, "MQTT service response is missing broker details")
        return None
    host = data.get("host")
    if not isinstance(host, str) or not host:
        _log_failure(warn, "MQTT service response is missing a broker host")
        return None
    try:
        port = int(data["port"])
    except (KeyError, TypeError, ValueError):
        _log_failure(warn, "MQTT service response has an invalid broker port")
        return None
    return MqttCredentials(
        host=host,
        port=port,
        username=_optional_str(data.get("username")),
        password=_optional_str(data.get("password")),
        ssl=bool(data.get("ssl")),
    )


def _log_failure(warn: bool, message: str, *args: object) -> None:
    level = logging.WARNING if warn else logging.DEBUG
    _LOGGER.log(level, message, *args)


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
