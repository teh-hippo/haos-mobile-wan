from __future__ import annotations

from typing import TYPE_CHECKING

from .gateway_cleanup import cleanup

if TYPE_CHECKING:
    from .gateway import GatewayEngine

MANAGEMENT_ERROR = "Management interface is unavailable"


def reconcile_without_management(
    engine: GatewayEngine,
    *,
    enabled: bool,
) -> None:
    engine.upstream_lifecycle.deactivate(None)
    engine._persist_state()
    cleanup(
        engine,
        preserve_enabled=enabled,
        preserve_host_protection=True,
        force=bool(engine.owned_state or engine.applied),
        owned_only=True,
    )
    with engine.lock:
        engine.last_downstream = None
        error = engine.management_error or MANAGEMENT_ERROR
        engine.last_safety_errors = [error]
        engine.last_error = error
    engine._record_upstream(None)
