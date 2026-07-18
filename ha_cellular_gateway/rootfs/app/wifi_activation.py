from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .command import RunCommand
from .nm_device import cached_ssids, disconnect_device, request_scan
from .nm_profile import NmProfile

ACTIVATION_BACKOFF_MIN = 5.0
ACTIVATION_BACKOFF_MAX = 60.0
SCAN_INTERVAL_SECONDS = 45.0

TARGET_ABSENT = "The hotspot network is not currently visible"
CONNECTING = "Associating with the hotspot network"
AUTH_FAILED = "The hotspot rejected the configured Wi-Fi password"


@dataclass(frozen=True)
class ActivationOutcome:
    phase: str
    message: str | None


class WifiActivator:
    def __init__(
        self,
        run: RunCommand,
        profile: NmProfile,
        target_ssid: str,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.run = run
        self.profile = profile
        self.target_ssid = target_ssid
        self.monotonic = monotonic
        self.sticky: str | None = None
        self._next_attempt = 0.0
        self._next_scan = 0.0
        self._backoff = ACTIVATION_BACKOFF_MIN
        self._fingerprint: tuple[object, ...] | None = None

    def reset(self) -> None:
        self.sticky = None
        self._next_attempt = 0.0
        self._next_scan = 0.0
        self._backoff = ACTIVATION_BACKOFF_MIN
        self._fingerprint = None

    def note_associated(self) -> None:
        self.sticky = None
        self._backoff = ACTIVATION_BACKOFF_MIN
        self._next_attempt = 0.0

    def drive(
        self,
        interface: str,
        active_uuid: str,
        device_fingerprint: tuple[object, ...],
        *,
        foreign_active: bool,
    ) -> ActivationOutcome:
        if device_fingerprint != self._fingerprint:
            self._fingerprint = device_fingerprint
            self.sticky = None
            self._backoff = ACTIVATION_BACKOFF_MIN
            self._next_attempt = 0.0
        if foreign_active:
            disconnect_device(self.run, interface)
            return ActivationOutcome("connecting", CONNECTING)
        if self.sticky is not None:
            return ActivationOutcome("auth_failed", self.sticky)
        if self.target_ssid not in cached_ssids(self.run, interface):
            self._maybe_scan(interface)
            return ActivationOutcome("waiting", TARGET_ABSENT)
        now = self.monotonic()
        if now < self._next_attempt:
            return ActivationOutcome("connecting", CONNECTING)
        return self._attempt(interface, now)

    def _maybe_scan(self, interface: str) -> None:
        now = self.monotonic()
        if now >= self._next_scan:
            request_scan(self.run, interface)
            self._next_scan = now + SCAN_INTERVAL_SECONDS

    def _attempt(self, interface: str, now: float) -> ActivationOutcome:
        result = self.run(
            "nmcli",
            "-w",
            "8",
            "connection",
            "up",
            "uuid",
            self.profile.spec.uuid,
            "ifname",
            interface,
            check=False,
            timeout=15,
        )
        self._next_attempt = now + self._backoff
        self._backoff = min(self._backoff * 2, ACTIVATION_BACKOFF_MAX)
        if self.profile.active_uuid(interface) == self.profile.spec.uuid:
            self.note_associated()
            return ActivationOutcome("associated", None)
        if _is_auth_failure(result.stderr):
            self.sticky = AUTH_FAILED
            return ActivationOutcome("auth_failed", AUTH_FAILED)
        return ActivationOutcome("connecting", CONNECTING)


def _is_auth_failure(stderr: str | None) -> bool:
    text = (stderr or "").lower()
    return "secrets" in text or "password" in text or "802-1x" in text
