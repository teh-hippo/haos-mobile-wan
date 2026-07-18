from __future__ import annotations

from collections.abc import Callable


class NmOwnershipJournal:
    def __init__(self) -> None:
        self.phase = "disabled"
        self.owned: dict[str, str] = {}
        self.persist: Callable[[], None] | None = None

    def load(self, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            return "Persistent NetworkManager profile ownership is invalid"
        if all(
            isinstance(key, str) and isinstance(uuid, str)
            for key, uuid in value.items()
        ):
            self.owned = dict(value)
            self.phase = "active"
            return None
        owned = value.get("owned")
        phase = value.get("phase")
        if not isinstance(owned, dict) or not all(
            isinstance(key, str) and isinstance(uuid, str)
            for key, uuid in owned.items()
        ) or not isinstance(phase, str):
            return "Persistent NetworkManager profile ownership is invalid"
        self.owned = dict(owned)
        self.phase = phase
        return None

    def state(self) -> dict[str, object] | None:
        if not self.owned and self.phase == "disabled":
            return None
        return {
            "phase": self.phase,
            "owned": dict(self.owned),
        }

    def set_persist(self, persist: Callable[[], None]) -> None:
        self.persist = persist

    def transition(self, phase: str) -> str | None:
        self.phase = phase
        return self._write()

    def claim(self, key: str, uuid: str) -> str | None:
        self.owned[key] = uuid
        return self._write()

    def release(self, key: str) -> str | None:
        self.owned.pop(key, None)
        return self._write()

    def _write(self) -> str | None:
        if self.persist is None:
            return None
        try:
            self.persist()
        except (OSError, ValueError) as err:
            return f"NetworkManager ownership journal failed: {err}"
        return None
