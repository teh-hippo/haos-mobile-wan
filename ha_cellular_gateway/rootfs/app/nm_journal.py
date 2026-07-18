from __future__ import annotations

from collections.abc import Callable

from .nm_profile import ProfileSpec


class NmOwnershipJournal:
    def __init__(self) -> None:
        self.phase = "disabled"
        self.owned: dict[str, dict[str, object]] = {}
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
            self.owned = {
                key: {"uuid": uuid, "fingerprint": {}}
                for key, uuid in value.items()
            }
            self.phase = "active"
            return None
        owned = value.get("owned")
        phase = value.get("phase")
        if (
            not isinstance(owned, dict)
            or not isinstance(phase, str)
            or not self._valid_owned(owned)
        ):
            return "Persistent NetworkManager profile ownership is invalid"
        self.owned = {
            key: dict(entry)
            for key, entry in owned.items()
            if isinstance(key, str) and isinstance(entry, dict)
        }
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

    def claim(self, key: str, spec: ProfileSpec) -> str | None:
        self.owned[key] = {
            "uuid": spec.uuid,
            "fingerprint": spec.fingerprint,
        }
        return self._write()

    def release(self, key: str) -> str | None:
        self.owned.pop(key, None)
        return self._write()

    def entry(self, key: str) -> dict[str, object] | None:
        return self.owned.get(key)

    def _write(self) -> str | None:
        if self.persist is None:
            return None
        try:
            self.persist()
        except (OSError, ValueError) as err:
            return f"NetworkManager ownership journal failed: {err}"
        return None

    @staticmethod
    def _valid_owned(value: dict[object, object]) -> bool:
        for key, entry in value.items():
            if not isinstance(key, str) or not isinstance(entry, dict):
                return False
            uuid = entry.get("uuid")
            fingerprint = entry.get("fingerprint")
            if not isinstance(uuid, str) or not isinstance(fingerprint, dict):
                return False
            if not all(
                isinstance(field, str) and isinstance(expected, str)
                for field, expected in fingerprint.items()
            ):
                return False
        return True
