from __future__ import annotations

import math
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .addon_options import read_options, set_enabled_option

if TYPE_CHECKING:
    from .config import GatewayConfig
    from .gateway import GatewayEngine

OptionWriter = Callable[[bool], str | None]
OptionsReader = Callable[[], dict[str, object] | None]

RETRY_SECONDS = 60


class AutoDisable:
    def __init__(
        self,
        config: GatewayConfig,
        state: dict[str, object],
        *,
        clock: Callable[[], float] = time.time,
        write_enabled: OptionWriter = set_enabled_option,
        read_current_options: OptionsReader = read_options,
    ) -> None:
        self.minutes = config.auto_disable_minutes
        self.clock = clock
        self.write_enabled = write_enabled
        self.read_current_options = read_current_options
        self.deadline: float | None = None
        self.pending = False
        self.option_error: str | None = None
        self.runtime_error: str | None = None
        self._retry_at = 0.0
        self.state_error = self._restore(state.get("auto_disable"))
        if not config.enabled or self.minutes == 0:
            self.clear()

    @property
    def latched(self) -> bool:
        return self.pending

    @property
    def error(self) -> str | None:
        return self.option_error or self.runtime_error or self.state_error

    @property
    def deadline_iso(self) -> str | None:
        if self.deadline is None:
            return None
        return datetime.fromtimestamp(self.deadline, UTC).isoformat()

    def state(self) -> dict[str, object] | None:
        payload: dict[str, object] = {}
        if self.deadline is not None:
            payload["deadline"] = self.deadline
        if self.pending:
            payload["pending"] = True
        if self.option_error:
            payload["error"] = self.option_error
        return payload or None

    def reconcile(self, engine: GatewayEngine) -> None:
        with engine.operation_lock:
            confirmed = self._confirm_persisted_disable()
            if confirmed:
                engine.enabled = False
                engine._persist_state()
                return
            changed = False
            if self.pending:
                engine.enabled = False
                changed = self._write_disable_if_due() or changed
                if changed:
                    engine._persist_state()
                return
            if not engine.enabled or self.minutes == 0:
                changed = self._clear_deadline() or changed
            elif engine.applied:
                changed = self._clear_deadline() or changed
            elif self.deadline is None:
                self.deadline = self.clock() + self.minutes * 60
                changed = True
            elif self.clock() >= self.deadline:
                self.deadline = None
                self.pending = True
                engine._persist_state()
                engine.enabled = False
                self._disable_runtime(engine)
                changed = self._write_disable_if_due(force=True) or changed
            if changed:
                engine._persist_state()

    def clear(self) -> None:
        self.deadline = None
        self.pending = False
        self.option_error = None
        self.runtime_error = None
        self._retry_at = 0.0

    def _restore(self, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            self.pending = True
            return "Persistent auto-disable state is invalid"
        deadline = value.get("deadline")
        pending = value.get("pending", False)
        error = value.get("error")
        if deadline is not None and (
            not isinstance(deadline, (int, float))
            or not math.isfinite(deadline)
            or deadline <= 0
        ):
            self.pending = True
            return "Persistent auto-disable deadline is invalid"
        if not isinstance(pending, bool):
            self.pending = True
            return "Persistent auto-disable latch is invalid"
        if error is not None and not isinstance(error, str):
            self.pending = True
            return "Persistent auto-disable error is invalid"
        self.deadline = float(deadline) if deadline is not None else None
        self.pending = pending
        self.option_error = error
        return None

    def _confirm_persisted_disable(self) -> bool:
        if not self.pending:
            return False
        options = self.read_current_options()
        if options is None or options.get("enabled") is not False:
            return False
        self.clear()
        return True

    def _clear_deadline(self) -> bool:
        if self.deadline is None:
            return False
        self.deadline = None
        return True

    def _disable_runtime(self, engine: GatewayEngine) -> None:
        try:
            engine.cleanup(preserve_host_protection=True)
        except (
            engine.gateway_error,
            OSError,
            subprocess.SubprocessError,
            ValueError,
        ) as err:
            self.runtime_error = f"Auto-disable cleanup failed: {err}"
        else:
            self.runtime_error = None
        management_interface = (
            engine.management.interface if engine.management else None
        )
        engine.upstream_lifecycle.deactivate(management_interface)
        if engine.upstream_lifecycle.error:
            self.runtime_error = engine.upstream_lifecycle.error

    def _write_disable_if_due(self, *, force: bool = False) -> bool:
        now = self.clock()
        if not force and now < self._retry_at:
            return False
        error = self.write_enabled(False)
        self._retry_at = now + RETRY_SECONDS
        if error == self.option_error:
            return False
        self.option_error = error
        return True
