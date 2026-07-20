from __future__ import annotations

from typing import TYPE_CHECKING

from .gateway_cleanup import cleanup

if TYPE_CHECKING:
    from .gateway import GatewayEngine

MANAGEMENT_ERROR = "Management interface is unavailable"


def reconcile_without_management(
    engine: GatewayEngine,
) -> None:
    engine.upstream_lifecycle.deactivate(None)
    engine._persist_state()
    cleanup(
        engine,
        preserve_host_protection=True,
        owned_only=True,
    )
    with engine.lock:
        engine.selection_state.downstream = None
        error = engine.lifecycle_state.management_error or MANAGEMENT_ERROR
        engine.selection_state.safety_errors = [error]
        engine.lifecycle_state.last_error = error
    engine._record_upstream(None)
