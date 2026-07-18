from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from .command import RunCommand
from .errors import GatewayError
from .nm_device import (
    DeviceState,
    device_identity,
    disconnect_device,
    read_device_state,
    resolve_interface,
    set_device_autoconnect,
)
from .nm_profile import NmProfile
from .networkmanager_invariants import main_default_present
from .nm_metadata import WifiProfileMetadata

CUSTODY_ERRORS = (GatewayError, OSError, subprocess.SubprocessError, ValueError)
MARKER_KEY = "cellgw.custody"

MANAGEMENT_GUARD = "The dedicated Wi-Fi adapter is the management interface"
DEVICE_MISSING = "The dedicated Wi-Fi adapter is not present"
DEVICE_UNMANAGED = "NetworkManager does not manage the dedicated Wi-Fi adapter"
RADIO_SOFT_OFF = "The Wi-Fi radio is turned off"
RADIO_HARD_OFF = "The Wi-Fi radio is hardware-blocked"
DISPLACE_FAILED = "A foreign Wi-Fi connection still controls the dedicated adapter"
RESTORE_PENDING = "The marked Wi-Fi adapter runtime restoration is pending"


@dataclass(frozen=True)
class CustodyMarker:
    stable_device_identity: str
    prior_device_autoconnect: bool
    prior_active_foreign_uuid: str | None

    def serialise(self) -> str:
        foreign = self.prior_active_foreign_uuid or ""
        return f"{self.stable_device_identity}|{int(self.prior_device_autoconnect)}|{foreign}"

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
        set(value) != {
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


class WifiCustodian:
    def __init__(
        self,
        config_interface: str,
        run: RunCommand,
        profile: NmProfile,
        *,
        metadata: WifiProfileMetadata,
        excluded_uuids: Callable[[], set[str]],
    ) -> None:
        self.configured_interface = config_interface
        self.run = run
        self.profile = profile
        self.metadata = metadata
        self.excluded_uuids = excluded_uuids
        self.interface: str | None = None
        self.marker: CustodyMarker | None = None
        self.blocker: str | None = None
        self._captured: DeviceState | None = None

    def resolve(
        self, management_interface: str | None, *, identity: str | None = None
    ) -> str | None:
        self.blocker = None
        if identity is None:
            identity = device_identity(self.run, self.configured_interface)
            interface = self.configured_interface
            if identity:
                interface = resolve_interface(self.run, identity) or interface
        else:
            try:
                interface = resolve_interface(self.run, identity)
            except CUSTODY_ERRORS:
                interface = None
        if interface is None:
            return None
        if management_interface is not None and interface == management_interface:
            self.blocker = MANAGEMENT_GUARD
            return None
        return interface

    def hold(
        self,
        management_interface: str | None,
        existing: CustodyMarker | None = None,
    ) -> list[str]:
        self.blocker = None
        interface = self.resolve(management_interface)
        if interface is None:
            return [self.blocker] if self.blocker else [DEVICE_MISSING]
        self.interface = interface
        try:
            state = read_device_state(self.run, interface)
        except CUSTODY_ERRORS:
            self.blocker = DEVICE_MISSING
            return [DEVICE_MISSING]
        blocker = self._prerequisite_blocker(state)
        if blocker:
            self.blocker = blocker
            return [blocker]
        self._captured = state
        if existing is not None and existing.stable_device_identity == state.identity:
            self.marker = existing
        else:
            self.marker = CustodyMarker(
                state.identity,
                state.autoconnect,
                self._foreign_uuid(state.active_uuid),
            )
        return []

    def apply_gate(self, persist: Callable[[], None]) -> list[str]:
        if self.interface is None or self.marker is None:
            return []
        self._write_profile_marker()
        persist()
        state = self._captured
        if state is not None and state.autoconnect:
            set_device_autoconnect(self.run, self.interface, False)
        if state is not None and self._foreign_uuid(state.active_uuid) is not None:
            disconnect_device(self.run, self.interface)
        return self._verify_clear()

    def release(
        self,
        management_interface: str | None,
        marker: CustodyMarker | None,
        persist: Callable[[], None],
    ) -> list[str]:
        if marker is not None:
            interface = self.resolve(
                management_interface, identity=marker.stable_device_identity
            )
            if interface is None:
                return [self.blocker or RESTORE_PENDING]
        else:
            interface = self.resolve(management_interface)
        if marker is not None and interface is not None:
            foreign = marker.prior_active_foreign_uuid
            if foreign and self._profile_exists(foreign):
                result = self.run(
                    "nmcli", "-w", "8", "connection", "up", "uuid", foreign,
                    check=False,
                )
                if result.returncode != 0:
                    return [RESTORE_PENDING]
        inspection = self.profile.inspect()
        if inspection.state != "missing" and (
            marker is not None or inspection.state == "exact"
        ):
            self.profile.deactivate()
            self.profile.delete()
        if marker is None or interface is None:
            return []
        if marker.prior_device_autoconnect:
            try:
                set_device_autoconnect(self.run, interface, True)
            except CUSTODY_ERRORS:
                return ["Wi-Fi adapter runtime restoration is incomplete"]
        self._clear_profile_marker()
        persist()
        return []

    def _prerequisite_blocker(self, state: DeviceState) -> str | None:
        if not state.radio_hardware:
            return RADIO_HARD_OFF
        if not state.radio_software:
            return RADIO_SOFT_OFF
        if not state.managed:
            return DEVICE_UNMANAGED
        return None

    def _foreign_uuid(self, active_uuid: str) -> str | None:
        if not active_uuid or active_uuid in self.excluded_uuids():
            return None
        return active_uuid

    def _verify_clear(self) -> list[str]:
        assert self.interface is not None
        if main_default_present(self.run, self.interface):
            return [DISPLACE_FAILED]
        active = self.profile.active_uuid(self.interface)
        if active and active not in self.excluded_uuids():
            return [DISPLACE_FAILED]
        return []

    def _profile_exists(self, uuid: str) -> bool:
        return self.run(
            "nmcli", "-g", "connection.uuid", "connection", "show", uuid, check=False
        ).returncode == 0

    def _write_profile_marker(self) -> None:
        assert self.marker is not None
        self.metadata.write(MARKER_KEY, self.marker.serialise())

    def _clear_profile_marker(self) -> None:
        self.metadata.clear(MARKER_KEY)

    def read_profile_marker(self) -> CustodyMarker | None:
        value = self.metadata.read(MARKER_KEY)
        if value is None:
            return None
        return parse_marker(value)
