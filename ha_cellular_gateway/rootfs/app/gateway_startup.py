from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from .gateway_cleanup import OPERATION_ERRORS, cleanup

if TYPE_CHECKING:
    from .gateway import GatewayEngine
    from .management import ManagementBaseline

_LOGGER = logging.getLogger(__name__)


def _recovery_pending(engine: GatewayEngine) -> bool:
    return bool(
        engine.lifecycle_state.owned_state
        or engine.upstream_lifecycle.state()
        or engine.wifi.state()
    )


def recover_from_restart(
    engine: GatewayEngine,
    management: ManagementBaseline | None,
) -> None:
    """Restore state left behind by an interrupted run."""
    config_error = engine.lifecycle_state.config_error
    recovery_pending = _recovery_pending(engine)
    started = time.monotonic()
    if recovery_pending:
        _LOGGER.warning(
            "Interrupted gateway state detected; recovering before reconciliation"
        )
    try:
        cleanup(
            engine,
            preserve_host_protection=(not config_error and management is not None),
            owned_only=bool(config_error or management is None),
        )
    except OPERATION_ERRORS:
        if recovery_pending:
            _LOGGER.exception(
                "Interrupted gateway recovery failed after %.1f seconds",
                time.monotonic() - started,
            )
        raise

    recovery: list[str] = []
    if not config_error:
        recovery = engine.upstream_lifecycle.recover(management)
        engine._persist_state()
        if recovery:
            with engine.lock:
                engine.lifecycle_state.last_error = "; ".join(recovery)

    with engine.lock:
        engine.lifecycle_state.startup_cleanup_pending = False
        if not config_error:
            engine.lifecycle_state.state_load_error = None

    if recovery:
        _LOGGER.warning(
            "Startup recovery remains incomplete after %.1f seconds: %s",
            time.monotonic() - started,
            "; ".join(recovery),
        )
    elif recovery_pending and not config_error:
        _LOGGER.info(
            "Interrupted gateway recovery completed in %.1f seconds",
            time.monotonic() - started,
        )
