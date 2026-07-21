from __future__ import annotations

import http.client
import os
from collections.abc import Callable

Connection = http.client.HTTPConnection
ConnectionFactory = Callable[[], Connection]
StopRequester = Callable[[], str | None]

SUPERVISOR_HOST = "supervisor"
STOP_PATH = "/addons/self/stop"
STOP_TIMEOUT = 10


def _default_connection() -> Connection:
    return http.client.HTTPConnection(SUPERVISOR_HOST, timeout=STOP_TIMEOUT)


def request_self_stop(
    *,
    token: str | None = None,
    connection_factory: ConnectionFactory | None = None,
) -> str | None:
    supervisor_token = (
        token if token is not None else os.environ.get("SUPERVISOR_TOKEN")
    )
    if not supervisor_token:
        return "Supervisor token is unavailable"
    connection = (connection_factory or _default_connection)()
    try:
        connection.request(
            "POST",
            STOP_PATH,
            headers={"Authorization": f"Bearer {supervisor_token}"},
        )
    except (OSError, http.client.HTTPException) as err:
        _close(connection)
        return f"{err}"
    _close(connection)
    return None


def _close(connection: Connection) -> None:
    try:
        connection.close()
    except OSError:
        pass
