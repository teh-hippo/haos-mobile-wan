from __future__ import annotations

from pathlib import Path

from .addon_options import UrlOpen, read_options, update_options
from .config import KNOWN_OPTION_KEYS, OPTIONS_PATH


def prune_legacy_options(
    *,
    token: str | None = None,
    urlopen: UrlOpen | None = None,
    options_path: Path = OPTIONS_PATH,
) -> str | None:
    existing = read_options(options_path)
    if existing is None:
        return None
    if not set(existing) - KNOWN_OPTION_KEYS:
        return None
    payload = {
        key: value for key, value in existing.items() if key in KNOWN_OPTION_KEYS
    }
    error = update_options(
        payload,
        label="options-migration",
        token=token,
        urlopen=urlopen,
    )
    if error and "Supervisor token is unavailable" in error:
        return None
    return error
