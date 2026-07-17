from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .config import OPTIONS_PATH

UrlOpen = Callable[..., object]
OPTIONS_URL = "http://supervisor/addons/self/options"


def read_options(path: Path = OPTIONS_PATH) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def update_options(
    options: dict[str, object],
    *,
    label: str,
    token: str | None = None,
    urlopen: UrlOpen | None = None,
) -> str | None:
    supervisor_token = (
        token if token is not None else os.environ.get("SUPERVISOR_TOKEN")
    )
    if not supervisor_token:
        return f"{label}: Supervisor token is unavailable"
    request = urllib.request.Request(
        OPTIONS_URL,
        data=json.dumps({"options": options}, separators=(",", ":")).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {supervisor_token}",
            "Content-Type": "application/json",
        },
    )
    opener = urlopen or urllib.request.urlopen
    try:
        opener(request, timeout=10)
    except urllib.error.HTTPError as err:
        err.close()
        return f"{label}: Supervisor rejected the update: HTTP {err.code}"
    except (OSError, urllib.error.URLError) as err:
        return f"{label}: {err}"
    return None


def set_enabled_option(
    enabled: bool,
    *,
    token: str | None = None,
    urlopen: UrlOpen | None = None,
    options_path: Path = OPTIONS_PATH,
) -> str | None:
    options = read_options(options_path)
    if options is None:
        return "Auto-disable option update failed: app options are unavailable"
    options["enabled"] = enabled
    return update_options(
        options,
        label="Auto-disable option update failed",
        token=token,
        urlopen=urlopen,
    )
