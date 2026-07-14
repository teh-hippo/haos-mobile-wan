from __future__ import annotations

import subprocess
import time
from typing import TYPE_CHECKING

from .errors import GatewayError, SafetyError

if TYPE_CHECKING:
    from .gateway import GatewayEngine

OPERATION_ERRORS = (GatewayError, OSError, subprocess.SubprocessError, ValueError)


def cleanup(
    engine: GatewayEngine,
    *,
    preserve_desired: bool = False,
    preserve_trial_deadline: bool = False,
    preserve_host_protection: bool = False,
    force: bool = False,
) -> None:
    with engine.operation_lock:
        with engine.lock:
            if engine.config.dry_run and not force:
                engine.mode = "disabled"
                engine.applied = False
                if not preserve_desired:
                    engine.desired_mode = "disabled"
                if not preserve_trial_deadline:
                    engine.trial_started_at = None
                    engine.trial_deadline = None
                engine._persist_state()
                return
            owned_state = engine.owned_state

        downstream = None
        try:
            downstream = engine.safety.find_downstream()
        except OPERATION_ERRORS:
            pass
        preserved_downstream = downstream
        if (
            not engine._protectable_downstream(preserved_downstream)
            and isinstance(engine.owned_state, dict)
        ):
            candidate = engine.owned_state.get("downstream")
            preserved_downstream = candidate if isinstance(candidate, str) else None
        if (
            not preserve_host_protection
            or not engine._protectable_downstream(preserved_downstream)
        ):
            preserved_downstream = None
        engine.dhcp.stop()
        engine.firewall.cleanup(preserved_downstream)

        ownerships: list[dict[str, object]] = []
        if owned_state:
            ownerships.append(owned_state)
        if downstream:
            current = engine.policy.ownership(downstream)
            if current not in ownerships:
                ownerships.append(current)
        for ownership in ownerships:
            engine.policy.cleanup(ownership)

        with engine.lock:
            engine.owned_state = None
            engine.mode = "disabled"
            engine.applied = False
            if not preserve_desired:
                engine.desired_mode = "disabled"
            if not preserve_trial_deadline:
                engine.trial_started_at = None
                engine.trial_deadline = None
            engine._persist_state()


def apply(
    engine: GatewayEngine,
    mode: str,
    *,
    recovering: bool = False,
) -> None:
    if mode not in {"trial", "active"}:
        raise GatewayError("Mode must be trial or active")
    if engine.config.dry_run:
        raise SafetyError("Mutation is disabled while dry_run is true")

    with engine.operation_lock:
        with engine.lock:
            if not recovering:
                engine.desired_mode = mode
                if mode == "trial":
                    engine.trial_started_at = time.time()
                    engine.trial_deadline = (
                        engine.trial_started_at + engine.config.trial_seconds
                    )
                else:
                    engine.trial_started_at = None
                    engine.trial_deadline = None

        downstream = engine.safety.find_downstream()
        upstream, upstream_errors = engine._resolve_upstream()
        errors = engine.safety.errors(
            downstream,
            upstream=upstream,
            upstream_errors=upstream_errors,
            state_error=engine.state_load_error,
        )
        with engine.lock:
            engine.last_downstream = downstream
            engine.last_upstream = upstream
            engine.last_safety_errors = errors
        if errors:
            cleanup(
                engine,
                preserve_desired=True,
                preserve_trial_deadline=recovering or mode == "trial",
            )
            message = "; ".join(errors)
            with engine.lock:
                engine.last_error = message
            raise SafetyError(message)
        assert downstream is not None
        assert upstream is not None

        cleanup(
            engine,
            preserve_desired=True,
            preserve_trial_deadline=mode == "trial",
        )
        with engine.lock:
            engine.owned_state = engine.policy.ownership(downstream, upstream)
            engine._persist_state()
        try:
            engine.policy.apply(downstream, upstream)
            engine.firewall.apply(downstream, upstream.interface)
            engine.dhcp.start(downstream)
        except OPERATION_ERRORS as err:
            cleanup(
                engine,
                preserve_desired=True,
                preserve_trial_deadline=mode == "trial",
            )
            message = f"Activation failed: {err}"
            with engine.lock:
                engine.last_error = message
            raise GatewayError(message) from err

        with engine.lock:
            engine.mode = mode
            engine.applied = True
            engine.last_error = None
            engine._persist_state()


def reconcile(engine: GatewayEngine, *, refresh_health: bool = False) -> None:
    try:
        with engine.operation_lock:
            with engine.lock:
                engine.last_reconcile = time.time()
                startup_cleanup_pending = engine.startup_cleanup_pending
                owned_state = bool(engine.owned_state)
                desired_mode = engine.desired_mode
                trial_deadline = engine.trial_deadline
                state_load_error = engine.state_load_error

            if startup_cleanup_pending:
                preserve_host_protection = False
                if desired_mode == "disabled" and not engine.config.dry_run:
                    candidates: list[str] = []
                    try:
                        downstream = engine.safety.find_downstream()
                    except OPERATION_ERRORS:
                        downstream = None
                    if engine._protectable_downstream(downstream):
                        candidates.append(downstream)
                    owned_downstream = (
                        engine.owned_state.get("downstream")
                        if isinstance(engine.owned_state, dict)
                        else None
                    )
                    if (
                        isinstance(owned_downstream, str)
                        and engine._protectable_downstream(owned_downstream)
                        and owned_downstream not in candidates
                    ):
                        candidates.append(owned_downstream)
                    preserve_host_protection = bool(
                        candidates
                        and engine.firewall.host_guard_chains_installed()
                    )
                cleanup(
                    engine,
                    preserve_desired=True,
                    preserve_trial_deadline=True,
                    preserve_host_protection=preserve_host_protection,
                    force=owned_state,
                )
                with engine.lock:
                    engine.state_load_error = None
                    engine.startup_cleanup_pending = False
                    state_load_error = None
            downstream = engine.safety.find_downstream()
            upstream, upstream_errors = engine._resolve_upstream()
            try:
                errors = engine.safety.errors(
                    downstream,
                    upstream=upstream,
                    upstream_errors=upstream_errors,
                    state_error=state_load_error,
                )
            except OPERATION_ERRORS as err:
                errors = [f"Safety inspection failed: {err}"]
            with engine.lock:
                engine.last_downstream = downstream
                engine.last_upstream = upstream
                engine.last_safety_errors = errors

            if (
                desired_mode == "trial"
                and trial_deadline
                and time.time() >= trial_deadline
            ):
                cleanup(engine, preserve_host_protection=True)
                with engine.lock:
                    engine.last_error = "Trial expired and was rolled back"
                return

            if desired_mode not in {"trial", "active"}:
                if engine.owned_state or engine.applied or engine.dhcp.running:
                    cleanup(
                        engine,
                        preserve_host_protection=engine._protectable_downstream(
                            downstream
                        ),
                        force=bool(engine.owned_state or engine.applied),
                    )
                elif (
                    not engine.config.dry_run
                    and engine._protectable_downstream(downstream)
                    and not engine.firewall.host_protection_installed(downstream)
                ):
                    engine.firewall.protect_host(downstream)
                return

            if errors:
                cleanup(
                    engine,
                    preserve_desired=True,
                    preserve_trial_deadline=True,
                    preserve_host_protection=engine._protectable_downstream(
                        downstream
                    ),
                )
                with engine.lock:
                    engine.last_error = "; ".join(errors)
                return

            if (
                engine.mode != desired_mode
                or not engine.policy.installed(downstream, upstream)
                or not engine.firewall.installed(
                    downstream,
                    upstream.interface if upstream else None,
                )
                or not engine.dhcp.running
            ):
                apply(engine, desired_mode, recovering=True)
    finally:
        if refresh_health:
            engine._refresh_health_if_due()
