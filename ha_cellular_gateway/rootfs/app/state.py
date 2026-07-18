from __future__ import annotations

import json
import os
from pathlib import Path


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[dict[str, object], str | None]:
        if not self.path.exists():
            return {}, None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            return {}, f"Cannot read persistent state: {err}"
        if not isinstance(data, dict):
            return {}, "Persistent state is not an object"
        return data, None

    def save(
        self,
        *,
        owned: dict[str, object] | None,
        auto_disable: dict[str, object] | None = None,
        profiles: dict[str, object] | None = None,
        management_interface: str | None = None,
    ) -> None:
        payload: dict[str, object] = {}
        if owned:
            payload["owned"] = owned
        if auto_disable:
            payload["auto_disable"] = auto_disable
        if profiles:
            payload["profiles"] = profiles
        if management_interface:
            payload["management_interface"] = management_interface

        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not payload:
            self.path.unlink(missing_ok=True)
            return

        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(
            json.dumps(payload, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.chmod(0o600)
        os.replace(temporary, self.path)
