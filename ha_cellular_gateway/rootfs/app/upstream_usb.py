from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from .command import RunCommand
from .errors import GatewayError
from .networkmanager import (
    LEASE_OWNER,
    NetworkManagerResult,
    NetworkManagerUsb,
)
from .nm_profile import ACTIVATION_COOLDOWN_SECONDS
from .nm_profile_specs import USB_DHCP_TIMEOUT_SECONDS
from .upstream_models import ResolvedUpstream

if TYPE_CHECKING:
    from .management import ManagementBaseline

UpstreamResolution = tuple[ResolvedUpstream | None, list[str]]


class UsbNetworkUpstream:
    LEASE_GRACE_SECONDS = max(
        ACTIVATION_COOLDOWN_SECONDS,
        USB_DHCP_TIMEOUT_SECONDS,
    ) + 5

    def __init__(
        self,
        run: RunCommand,
        network_manager: NetworkManagerUsb,
        *,
        label: str,
        ready_state: str,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.run = run
        self.nm = network_manager
        self.label = label
        self.ready_state = ready_state
        self._monotonic = monotonic
        self.pairing_state = "not_applicable"
        self.pairing_message: str | None = None
        self.interface: str | None = None
        self.carrier: bool | None = None
        self.lease_owner: str | None = None
        self.fallback_safe = True
        self._last_lease: tuple[ResolvedUpstream, float] | None = None

    @property
    def profile_key(self) -> str:
        return self.nm.profile.spec.key

    @property
    def profile_drift_error(self) -> str:
        return f"The app-owned {self.label} profile has unexpected settings"

    @property
    def cleanup_error_label(self) -> str:
        return f"{self.label} cleanup failed"

    @property
    def unavailable_message(self) -> str:
        return f"{self.label} is unavailable"

    def runtime_status(self) -> dict[str, object]:
        return {
            "upstream_pairing_state": self.pairing_state,
            "upstream_pairing_message": self.pairing_message,
            "upstream_device_udid": None,
            "upstream_runtime_interface": self.interface,
            "upstream_carrier": self.carrier,
            "upstream_lockdown_path": None,
            "upstream_lease_owner": self.lease_owner,
        }

    def fallback_allowed(self) -> bool:
        return self.fallback_safe

    def resolve(
        self,
        management: ManagementBaseline | None = None,
        downstream_interface: str | None = None,
    ) -> UpstreamResolution:
        raise NotImplementedError

    def cleanup(self) -> None:
        self._forget_lease()
        self._reset_status()

    def _begin(self) -> None:
        self._reset_status()
        self.pairing_state = "not_ready"

    def _resolve_network(
        self,
        interface: str,
        carrier: bool | None,
        management: ManagementBaseline | None,
        *,
        carrier_state: str,
        carrier_message: str,
    ) -> UpstreamResolution:
        self.interface = interface
        self.carrier = carrier
        if carrier is False:
            self._forget_lease()
            return self._fail(carrier_state, carrier_message)
        try:
            result = self.nm.inspect(interface, management)
        except (
            GatewayError,
            OSError,
            subprocess.SubprocessError,
            ValueError,
        ) as err:
            grace = self._grace_lease()
            if grace is not None:
                return grace, []
            return self._fail(
                "waiting_for_profile",
                f"NetworkManager {self.label} inspection is unavailable: {err}",
            )
        return self._consume(result)

    def _consume(self, result: NetworkManagerResult) -> UpstreamResolution:
        if result.state == "active":
            assert result.upstream is not None
            self._last_lease = (result.upstream, self._monotonic())
            self.lease_owner = LEASE_OWNER
            self.pairing_state = self.ready_state
            self.pairing_message = None
            return result.upstream, []
        if result.state == "waiting":
            grace = self._grace_lease()
            if grace is not None:
                self.lease_owner = LEASE_OWNER
                self.pairing_state = self.ready_state
                self.pairing_message = None
                return grace, []
            assert result.error is not None
            return self._fail("waiting_for_profile", result.error)
        self._forget_lease()
        state = "profile_conflict" if result.state == "foreign" else "invalid_lease"
        assert result.error is not None
        return self._fail(state, result.error, safe=False)

    def _fail(
        self,
        state: str,
        message: str,
        *,
        safe: bool = True,
    ) -> UpstreamResolution:
        self.pairing_state = state
        self.pairing_message = message
        if not safe:
            self.fallback_safe = False
        return None, [message]

    def _grace_lease(self) -> ResolvedUpstream | None:
        if self._last_lease is None:
            return None
        upstream, seen = self._last_lease
        if (
            self._monotonic() - seen < self.LEASE_GRACE_SECONDS
            and self.nm.continuity(upstream)
        ):
            return upstream
        self._last_lease = None
        return None

    def _forget_lease(self) -> None:
        self._last_lease = None

    def _reset_status(self) -> None:
        self.pairing_state = "not_applicable"
        self.pairing_message = None
        self.interface = None
        self.carrier = None
        self.lease_owner = None
        self.fallback_safe = True
