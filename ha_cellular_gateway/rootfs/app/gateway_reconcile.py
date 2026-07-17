from __future__ import annotations

import subprocess
import time
from typing import TYPE_CHECKING

from .errors import GatewayError, SafetyError
from .gateway_cleanup import cleanup
from .gateway_dormant import reconcile_disabled
from .gateway_transition import cleanup_changed_ownership
from .hotspot import classify_wifi_upstream
from .lifecycle import log_upstream_transitions, wifi_interface_status

if TYPE_CHECKING:
    from .gateway import GatewayEngine
    from .upstream_models import ResolvedUpstream

OPERATION_ERRORS = (GatewayError, OSError, subprocess.SubprocessError, ValueError)


def _protect_host(engine: GatewayEngine, downstream: str | None) -> None:
    if (
        engine._protectable_downstream(downstream)
        and not engine.firewall.host_protection_installed(downstream)
    ):
        assert downstream is not None
        engine.firewall.protect_host(downstream)


def apply(
    engine: GatewayEngine,
    *,
    recovering: bool = False,
    upstream: ResolvedUpstream | None = None,
    upstream_errors: list[str] | None = None,
) -> None:
    if engine.config_error:
        raise GatewayError(engine.config_error)

    with engine.operation_lock:
        with engine.lock:
            if not recovering:
                engine.enabled = True

        management = engine._resolve_management()
        downstream = engine.safety.find_downstream(
            management.interface if management else None
        )
        if upstream_errors is None:
            upstream, upstream_errors = engine._resolve_upstream()
        cleanup_changed_ownership(engine, downstream, upstream)
        address_owned = engine.downstream.owns_address(
            engine.owned_state,
            downstream,
        )
        errors = engine.safety.errors(
            downstream,
            management=management,
            upstream=upstream,
            upstream_errors=upstream_errors,
            state_error=engine.state_load_error,
            downstream_address_owned=address_owned,
        )
        errors = classify_wifi_upstream(
            engine.config, errors, engine._interface_status
        )
        with engine.lock:
            engine.last_downstream = downstream
            engine.last_safety_errors = errors
        engine._record_upstream(upstream)
        if errors:
            cleanup(
                engine,
                preserve_enabled=True,
                preserve_host_protection=True,
            )
            _protect_host(engine, downstream)
            message = "; ".join(errors)
            with engine.lock:
                engine.last_error = message
            raise SafetyError(message)
        assert downstream is not None
        assert upstream is not None

        cleanup(
            engine,
            preserve_enabled=True,
            preserve_host_protection=True,
        )
        with engine.lock:
            engine.owned_state = engine.policy.ownership(downstream, upstream)
            engine.owned_state["downstream_address_owned"] = True
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
                preserve_enabled=True,
                preserve_host_protection=True,
            )
            message = f"Activation failed: {err}"
            with engine.lock:
                engine.last_error = message
            raise GatewayError(message) from err

        with engine.lock:
            engine.applied = True
            engine.active_connection = upstream.connection
            engine.last_error = None
            engine._persist_state()


def reconcile(engine: GatewayEngine, *, refresh_health: bool = False) -> None:
    try:
        with engine.operation_lock:
            with engine.lock:
                engine.last_reconcile = time.time()
                startup_cleanup_pending = engine.startup_cleanup_pending
                owned_state = engine.owned_state
                enabled = engine.enabled
                state_load_error = engine.state_load_error

            management = engine._resolve_management()

            if startup_cleanup_pending:
                cleanup(
                    engine,
                    preserve_enabled=True,
                    preserve_host_protection=not engine.config_error,
                    force=bool(owned_state),
                    owned_only=bool(engine.config_error),
                )
                with engine.lock:
                    engine.startup_cleanup_pending = False
                    if not engine.config_error:
                        engine.state_load_error = None
                        state_load_error = None
            if engine.config_error:
                with engine.lock:
                    engine.last_downstream = None
                    engine.last_safety_errors = [engine.config_error]
                    engine.last_error = engine.config_error
                engine._record_upstream(None)
                return
            downstream = engine.safety.find_downstream(
                management.interface if management else None
            )
            if not enabled:
                reconcile_disabled(
                    engine,
                    downstream,
                    management.interface if management else None,
                )
                return

            engine.upstream_lifecycle.activate(
                management.interface if management else None
            )
            engine.connection.wifi_error = engine.upstream_lifecycle.error
            upstream, upstream_errors = engine._resolve_upstream()
            cleanup_changed_ownership(
                engine,
                downstream,
                upstream,
            )
            try:
                errors = engine.safety.errors(
                    downstream,
                    management=management,
                    upstream=upstream,
                    upstream_errors=upstream_errors,
                    state_error=state_load_error,
                    downstream_address_owned=engine.downstream.owns_address(
                        engine.owned_state,
                        downstream,
                    ),
                )
            except OPERATION_ERRORS as err:
                errors = [f"Safety inspection failed: {err}"]
            wifi_status = wifi_interface_status(engine)
            errors = classify_wifi_upstream(engine.config, errors, lambda: wifi_status)
            with engine.lock:
                engine.last_downstream = downstream
                engine.last_safety_errors = errors
            engine._record_upstream(upstream)
            log_upstream_transitions(engine, upstream, wifi_status)

            if errors:
                cleanup(
                    engine,
                    preserve_enabled=True,
                    preserve_host_protection=True,
                )
                _protect_host(engine, downstream)
                with engine.lock:
                    engine.last_error = "; ".join(errors)
                return

            if (
                not engine.applied
                or not engine.policy.installed(downstream, upstream)
                or not engine.firewall.installed(
                    downstream,
                    upstream.interface if upstream else None,
                )
                or not engine.dhcp.running
            ):
                apply(
                    engine,
                    recovering=True,
                    upstream=upstream,
                    upstream_errors=upstream_errors,
                )
    finally:
        if refresh_health:
            engine._refresh_health_if_due()
