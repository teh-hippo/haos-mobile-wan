from __future__ import annotations

import subprocess
import time
from typing import TYPE_CHECKING

from .errors import GatewayError, SafetyError
from .gateway_cleanup import cleanup
from .gateway_config_failure import handle_config_error
from .gateway_management import reconcile_without_management
from .gateway_safety_evaluation import (
    evaluate_safety,
    handle_unsafe_state,
    record_evaluation,
)
from .gateway_startup import recover_from_restart
from .gateway_transition import cleanup_changed_ownership

if TYPE_CHECKING:
    from .gateway import GatewayEngine
    from .management import ManagementBaseline
    from .upstream_models import ResolvedUpstream

OPERATION_ERRORS = (GatewayError, OSError, subprocess.SubprocessError, ValueError)


def apply(
    engine: GatewayEngine,
    *,
    upstream: ResolvedUpstream | None = None,
    upstream_errors: list[str] | None = None,
) -> None:
    if engine.lifecycle_state.config_error:
        raise GatewayError(engine.lifecycle_state.config_error)

    with engine.operation_lock:
        management = engine._resolve_management()
        downstream = engine.safety.find_downstream(
            management.interface if management else None
        )
        if upstream_errors is None:
            upstream, upstream_errors = engine._resolve_upstream(downstream)
        cleanup_changed_ownership(engine, downstream, upstream)
        address_owned = engine.downstream.owns_address(
            engine.lifecycle_state.owned_state,
            downstream,
        )
        errors = engine.safety.errors(
            downstream,
            management=management,
            upstream=upstream,
            upstream_errors=upstream_errors,
            state_error=engine.lifecycle_state.state_load_error,
            downstream_address_owned=address_owned,
        )
        with engine.lock:
            engine.selection_state.downstream = downstream
            engine.selection_state.safety_errors = errors
        engine._record_upstream(upstream)
        if errors:
            message = handle_unsafe_state(engine, downstream, errors)
            raise SafetyError(message)
        assert downstream is not None
        assert upstream is not None

        cleanup(
            engine,
            preserve_host_protection=True,
        )
        with engine.lock:
            engine.lifecycle_state.owned_state = engine.policy.ownership(
                downstream, upstream
            )
            engine.lifecycle_state.owned_state["downstream_address_owned"] = True
            engine._persist_state()
        try:
            engine.firewall.protect_host(downstream)
            engine.downstream.apply(downstream)
            engine.policy.apply(downstream, upstream)
            engine.firewall.apply(downstream, upstream.interface)
            engine.dhcp.start(downstream)
        except OPERATION_ERRORS as err:
            cleanup(
                engine,
                preserve_host_protection=True,
            )
            message = f"Activation failed: {err}"
            with engine.lock:
                engine.lifecycle_state.last_error = message
            raise GatewayError(message) from err

        with engine.lock:
            engine.lifecycle_state.applied = True
            engine.selection_state.active_connection = upstream.connection
            engine.lifecycle_state.last_error = None
            engine._persist_state()


def _needs_apply(
    engine: GatewayEngine,
    downstream: str | None,
    upstream: ResolvedUpstream | None,
) -> bool:
    return (
        not engine.lifecycle_state.applied
        or not engine.policy.installed(downstream, upstream)
        or not engine.firewall.installed(
            downstream,
            upstream.interface if upstream else None,
        )
        or not engine.dhcp.running
    )


def _reconcile_with_management(
    engine: GatewayEngine,
    management: ManagementBaseline,
) -> None:
    evaluation = evaluate_safety(engine, management)
    record_evaluation(engine, evaluation)

    if evaluation.errors:
        handle_unsafe_state(engine, evaluation.downstream, evaluation.errors)
        return

    if _needs_apply(engine, evaluation.downstream, evaluation.upstream):
        apply(
            engine,
            upstream=evaluation.upstream,
            upstream_errors=evaluation.upstream_errors,
        )


def reconcile(engine: GatewayEngine, *, refresh_health: bool = False) -> None:
    try:
        with engine.operation_lock:
            if engine.stop_event.is_set():
                return
            with engine.lock:
                engine.lifecycle_state.last_reconcile = time.time()
                startup_cleanup_pending = engine.lifecycle_state.startup_cleanup_pending

            if engine.auto_disable.pending:
                return

            management = engine._resolve_management()

            if startup_cleanup_pending:
                recover_from_restart(engine, management)

            if engine.lifecycle_state.config_error:
                handle_config_error(engine)
                return
            if management is None:
                reconcile_without_management(engine)
                return

            _reconcile_with_management(engine, management)
    finally:
        if refresh_health and not engine.stop_event.is_set():
            engine._refresh_health_if_due()
