from __future__ import annotations

import subprocess
import time
from typing import TYPE_CHECKING

from .errors import GatewayError, SafetyError
from .gateway_cleanup import cleanup

if TYPE_CHECKING:
    from .gateway import GatewayEngine

OPERATION_ERRORS = (GatewayError, OSError, subprocess.SubprocessError, ValueError)


def _protect_host(engine: GatewayEngine, downstream: str | None) -> None:
    if (
        not engine.config.dry_run
        and engine._protectable_downstream(downstream)
        and not engine.firewall.host_protection_installed(downstream)
    ):
        assert downstream is not None
        engine.firewall.protect_host(downstream)


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
            if mode == "trial" and (
                not recovering or engine.trial_deadline is None
            ):
                engine.trial_started_at = time.time()
                engine.trial_deadline = (
                    engine.trial_started_at + engine.config.trial_seconds
                )
            elif mode == "active":
                engine.trial_started_at = None
                engine.trial_deadline = None

        downstream = engine.safety.find_downstream()
        upstream, upstream_errors = engine._resolve_upstream()
        address_owned = engine.downstream.owns_address(
            engine.owned_state,
            downstream,
        )
        errors = engine.safety.errors(
            downstream,
            upstream=upstream,
            upstream_errors=upstream_errors,
            state_error=engine.state_load_error,
            downstream_address_owned=address_owned,
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
            preserve_desired=True,
            preserve_trial_deadline=mode == "trial",
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
                preserve_desired=True,
                preserve_trial_deadline=mode == "trial",
                preserve_host_protection=True,
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
                owned_state = engine.owned_state
                desired_mode = engine.desired_mode
                trial_deadline = engine.trial_deadline
                state_load_error = engine.state_load_error

            if startup_cleanup_pending:
                cleanup(
                    engine,
                    preserve_desired=True,
                    preserve_trial_deadline=True,
                    preserve_host_protection=not engine.config.dry_run,
                    force=bool(owned_state),
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
                    downstream_address_owned=engine.downstream.owns_address(
                        engine.owned_state,
                        downstream,
                    ),
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
                _protect_host(engine, downstream)
                with engine.lock:
                    engine.last_error = "Trial expired and was rolled back"
                return

            if desired_mode not in {"trial", "active"}:
                managed_chains = (
                    ("iptables", engine.firewall.INPUT_CHAIN),
                    ("ip6tables", engine.firewall.INPUT6_CHAIN),
                    ("iptables", engine.firewall.FORWARD_CHAIN),
                    ("ip6tables", engine.firewall.FORWARD6_CHAIN),
                )
                present_chains = {
                    (family, chain)
                    for family, chain in managed_chains
                    if engine.firewall.chain_exists(family, chain)
                }
                forwarding_present = any(
                    chain in {
                        engine.firewall.FORWARD_CHAIN,
                        engine.firewall.FORWARD6_CHAIN,
                    }
                    for _, chain in present_chains
                )
                host_guard_needs_repair = bool(present_chains) and not (
                    engine.firewall.host_protection_installed(downstream)
                )
                if (
                    engine.owned_state
                    or engine.applied
                    or engine.dhcp.running
                    or forwarding_present
                    or host_guard_needs_repair
                ):
                    cleanup(
                        engine,
                        preserve_host_protection=True,
                        force=bool(engine.owned_state or engine.applied),
                    )
                _protect_host(engine, downstream)
                return

            if errors:
                cleanup(
                    engine,
                    preserve_desired=True,
                    preserve_trial_deadline=True,
                    preserve_host_protection=True,
                )
                _protect_host(engine, downstream)
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
