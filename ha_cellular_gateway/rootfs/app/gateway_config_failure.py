from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .gateway import GatewayEngine


def handle_config_error(engine: GatewayEngine) -> None:
    config_error = engine.lifecycle_state.config_error
    assert config_error is not None
    with engine.lock:
        engine.selection_state.downstream = None
        engine.selection_state.safety_errors = [config_error]
        engine.lifecycle_state.last_error = config_error
    engine._record_upstream(None)
