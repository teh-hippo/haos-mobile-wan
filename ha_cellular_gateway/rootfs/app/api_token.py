from __future__ import annotations

import secrets
from pathlib import Path

from .config import TOKEN_PATH


def load_or_create_token(path: Path = TOKEN_PATH) -> str:
    if path.exists():
        path.chmod(0o600)
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token := secrets.token_urlsafe(32), encoding="utf-8")
    path.chmod(0o600)
    return token
