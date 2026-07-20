from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .errors import GatewayError
from .gateway_cleanup import cleanup
from .gateway_transition import cleanup_changed_ownership
from .lifecycle import log_upstream_transitions, wifi_interface_status

if TYPE_CHECKING:
    from .gateway import GatewayEngine
    from .management import ManagementBaseline
    from .upstream_models import ResolvedUpstream

OPERATION_ERRORS = (GatewayError, OSError, subprocess.SubprocessError, ValueError)


@dataclass
class SafetyEvaluation:
    """The downstream/upstream pairing and safety findings for one reconcile pass."""

    downstream: str | None
    upstream: ResolvedUpstream | None
    upstream_errors: list[str]
    errors: list[str]
    wifi_status: dict[str, object] | None


def evaluate_safety(
    engine: GatewayEngine,
    management: ManagementBaseline,
) -> SafetyEvaluation:
    downstream = engine.safety.find_downstream(management.interface)
    engine.upstream_lifecycle.activate(management)
    engine._persist_state()
    engine.connection.wifi_error = engine.upstream_lifecycle.error
    upstream, upstream_errors = engine._resolve_upstream(downstream)
    cleanup_changed_ownership(engine, downstream, upstream)
    try:
        errors = engine.safety.errors(
            downstream,
            management=management,
            upstream=upstream,
            upstream_errors=upstream_errors,
            state_error=engine.lifecycle_state.state_load_error,
            downstream_address_owned=engine.downstream.owns_address(
                engine.lifecycle_state.owned_state,
                downstream,
            ),
        )
    except OPERATION_ERRORS as err:
        errors = [f"Safety inspection failed: {err}"]
    wifi_status = wifi_interface_status(engine)
    return SafetyEvaluation(downstream, upstream, upstream_errors, errors, wifi_status)


def record_evaluation(engine: GatewayEngine, evaluation: SafetyEvaluation) -> None:
    with engine.lock:
        engine.selection_state.downstream = evaluation.downstream
        engine.selection_state.safety_errors = evaluation.errors
    engine._record_upstream(evaluation.upstream)
    log_upstream_transitions(engine, evaluation.upstream, evaluation.wifi_status)


def protect_host_if_needed(engine: GatewayEngine, downstream: str | None) -> None:
    if engine._protectable_downstream(
        downstream
    ) and not engine.firewall.host_protection_installed(downstream):
        assert downstream is not None
        engine.firewall.protect_host(downstream)


def handle_unsafe_state(
    engine: GatewayEngine,
    downstream: str | None,
    errors: list[str],
) -> str:
    cleanup(engine, preserve_host_protection=True)
    protect_host_if_needed(engine, downstream)
    message = "; ".join(errors)
    with engine.lock:
        engine.lifecycle_state.last_error = message
    return message
