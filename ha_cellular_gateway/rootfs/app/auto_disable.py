from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .addon_stop import StopRequester, request_self_stop

if TYPE_CHECKING:
    from .config import GatewayConfig
    from .gateway import GatewayEngine

RETRY_SECONDS = 60


class AutoDisable:
    """Stop the add-on when it never reaches an applied gateway in time.

    While the add-on runs without a successfully applied data plane, a fixed
    deadline counts down. Once the gateway applies, the deadline clears. On
    expiry the controller latches an in-memory stop-pending state, releases
    every owned network resource, then asks Supervisor to stop the add-on.
    Nothing is persisted, so an explicit later manual start is a fresh
    session with a fresh timer.
    """

    def __init__(
        self,
        config: GatewayConfig,
        *,
        clock: Callable[[], float] = time.time,
        stop_requester: StopRequester = request_self_stop,
    ) -> None:
        self.minutes = config.auto_disable_minutes
        self.clock = clock
        self.stop_requester = stop_requester
        self.deadline: float | None = None
        self.pending = False
        self.cleanup_error: str | None = None
        self.persistence_error: str | None = None
        self.stop_error: str | None = None
        self._retry_at = 0.0

    @property
    def error(self) -> str | None:
        return self.cleanup_error or self.persistence_error or self.stop_error

    @property
    def deadline_iso(self) -> str | None:
        if self.deadline is None:
            return None
        return datetime.fromtimestamp(self.deadline, UTC).isoformat()

    def reconcile(self, engine: GatewayEngine) -> None:
        with engine.operation_lock:
            if self.pending:
                self._drive_stop(engine)
                return
            if self.minutes == 0 or engine.applied:
                self.deadline = None
                return
            if self.deadline is None:
                self.deadline = self.clock() + self.minutes * 60
                return
            if self.clock() >= self.deadline:
                self.deadline = None
                self.pending = True
                self._drive_stop(engine)

    def _drive_stop(self, engine: GatewayEngine) -> None:
        if not self._release(engine):
            return
        now = self.clock()
        if now < self._retry_at:
            return
        self._retry_at = now + RETRY_SECONDS
        error = self.stop_requester()
        self.stop_error = f"Auto-stop request failed: {error}" if error else None

    def _release(self, engine: GatewayEngine) -> bool:
        cleanup_ok = True
        try:
            engine.cleanup(preserve_host_protection=True)
        except (
            engine.gateway_error,
            OSError,
            subprocess.SubprocessError,
            ValueError,
        ) as err:
            cleanup_ok = False
            self.cleanup_error = f"Auto-disable cleanup failed: {err}"
        engine.upstream_lifecycle.deactivate(engine.management)
        self._persist(engine)
        lifecycle_error = engine.upstream_lifecycle.error
        if lifecycle_error:
            self.cleanup_error = lifecycle_error
            return False
        if not cleanup_ok:
            return False
        self.cleanup_error = None
        return True

    def _persist(self, engine: GatewayEngine) -> None:
        try:
            engine._persist_state()
        except (OSError, ValueError) as err:
            self.persistence_error = (
                f"Auto-disable state persistence failed: {err}"
            )
        else:
            self.persistence_error = None
