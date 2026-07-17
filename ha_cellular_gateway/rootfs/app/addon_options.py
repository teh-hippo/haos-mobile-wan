from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .config import OPTIONS_PATH

_LOGGER = logging.getLogger(__name__)

UrlOpen = Callable[..., object]

OPTIONS_URL = "http://supervisor/addons/self/options"
RESTART_URL = "http://supervisor/addons/self/restart"


def set_mobile_connection(
    label: str,
    *,
    token: str | None = None,
    urlopen: UrlOpen | None = None,
    options_path: Path = OPTIONS_PATH,
) -> None:
    options = _read_options(options_path)
    if options is None:
        _LOGGER.warning("Cannot change connection method: options are unreadable")
        return
    if options.get("mobile_connection") == label:
        return
    supervisor_token = (
        token if token is not None else os.environ.get("SUPERVISOR_TOKEN")
    )
    if not supervisor_token:
        _LOGGER.warning("Cannot change connection method: Supervisor token is missing")
        return
    options["mobile_connection"] = label
    opener = urlopen or urllib.request.urlopen
    if not _post(opener, OPTIONS_URL, {"options": options}, supervisor_token):
        return
    _post(opener, RESTART_URL, None, supervisor_token)


def _post(
    opener: UrlOpen,
    url: str,
    payload: dict[str, object] | None,
    token: str,
) -> bool:
    headers = {"Authorization": f"Bearer {token}"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        opener(request, timeout=10)
    except urllib.error.HTTPError as err:
        err.close()
        _LOGGER.warning("Supervisor rejected %s: HTTP %s", url, err.code)
        return False
    except (OSError, urllib.error.URLError) as err:
        _LOGGER.warning("Supervisor request to %s failed: %s", url, err)
        return False
    return True


def _read_options(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
