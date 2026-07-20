from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CustodyMarker:
    stable_device_identity: str
    prior_device_autoconnect: bool
    prior_active_foreign_uuid: str | None

    def serialise(self) -> str:
        foreign = self.prior_active_foreign_uuid or ""
        return (
            f"{self.stable_device_identity}|"
            f"{int(self.prior_device_autoconnect)}|{foreign}"
        )

    def as_state(self) -> dict[str, object]:
        return {
            "stable_device_identity": self.stable_device_identity,
            "prior_device_autoconnect": self.prior_device_autoconnect,
            "prior_active_foreign_uuid": self.prior_active_foreign_uuid,
        }


def parse_marker(value: object) -> CustodyMarker | None:
    if isinstance(value, str):
        parts = value.split("|")
        if len(parts) != 3 or not parts[0]:
            return None
        return CustodyMarker(parts[0], parts[1] == "1", parts[2] or None)
    if not isinstance(value, dict):
        return None
    identity = value.get("stable_device_identity")
    autoconnect = value.get("prior_device_autoconnect")
    foreign = value.get("prior_active_foreign_uuid")
    if (
        set(value)
        != {
            "stable_device_identity",
            "prior_device_autoconnect",
            "prior_active_foreign_uuid",
        }
        or not isinstance(identity, str)
        or not identity
        or not isinstance(autoconnect, bool)
        or not (foreign is None or isinstance(foreign, str))
    ):
        return None
    return CustodyMarker(identity, autoconnect, foreign or None)
