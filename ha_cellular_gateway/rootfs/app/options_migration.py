from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .config import KNOWN_OPTION_KEYS, OPTIONS_PATH

UrlOpen = Callable[..., object]


def prune_legacy_options(
    *,
    token: str | None = None,
    urlopen: UrlOpen | None = None,
    options_path: Path = OPTIONS_PATH,
) -> str | None:
    existing = _read_options(options_path)
    if existing is None:
        return None
    if not set(existing) - KNOWN_OPTION_KEYS:
        return None
    supervisor_token = (
        token if token is not None else os.environ.get("SUPERVISOR_TOKEN")
    )
    if not supervisor_token:
        return None
    payload = {
        key: value for key, value in existing.items() if key in KNOWN_OPTION_KEYS
    }
    request = urllib.request.Request(
        "http://supervisor/addons/self/options",
        data=json.dumps({"options": payload}).encode(),
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
        return f"options-migration: Supervisor rejected the update: HTTP {err.code}"
    except (OSError, urllib.error.URLError) as err:
        return f"options-migration: {err}"
    return None


def _read_options(path: Path) -> dict[str, object] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
