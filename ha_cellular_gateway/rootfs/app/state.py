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
        trial_started_at: float | None,
        trial_deadline: float | None,
    ) -> None:
        payload: dict[str, object] = {}
        if owned:
            payload["owned"] = owned
        if trial_started_at is not None and trial_deadline is not None:
            payload["trial"] = {
                "started_at": trial_started_at,
                "deadline": trial_deadline,
            }

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
