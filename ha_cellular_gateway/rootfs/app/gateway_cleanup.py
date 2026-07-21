from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from .errors import GatewayError

if TYPE_CHECKING:
    from .gateway import GatewayEngine

_LOGGER = logging.getLogger(__name__)

OPERATION_ERRORS = (GatewayError, OSError, subprocess.SubprocessError, ValueError)


@dataclass
class CleanupPlan:
    owned_state: dict[str, object] | None
    downstream: str | None
    protected_downstream: str | None
    ownerships: list[dict[str, object]]


def _attempt(
    errors: list[str],
    label: str,
    action: Callable[[], None],
) -> None:
    try:
        action()
    except OPERATION_ERRORS as err:
        errors.append(f"{label}: {err}")


def _discover_downstream(
    engine: GatewayEngine,
    *,
    owned_only: bool,
) -> str | None:
    if owned_only:
        return None
    try:
        return engine.safety.find_downstream(
            engine.management.interface if engine.management else None
        )
    except OPERATION_ERRORS as err:
        _LOGGER.warning(
            "Downstream discovery failed during cleanup; "
            "continuing teardown from persisted ownership: %s",
            err,
        )
        return None


def _resolve_protected_downstream(
    engine: GatewayEngine,
    *,
    downstream: str | None,
    owned_state: dict[str, object] | None,
    preserve_host_protection: bool,
) -> str | None:
    protected_downstream = downstream
    if (
        preserve_host_protection
        and not engine._protectable_downstream(protected_downstream)
        and engine._protectable_downstream(engine.selection_state.downstream)
    ):
        protected_downstream = engine.selection_state.downstream
    if not engine._protectable_downstream(protected_downstream) and isinstance(
        owned_state, dict
    ):
        candidate = owned_state.get("downstream")
        protected_downstream = candidate if isinstance(candidate, str) else None
    if not (
        preserve_host_protection or engine.downstream.owns_address(owned_state)
    ) or not engine._protectable_downstream(protected_downstream):
        protected_downstream = None
    return protected_downstream


def _plan_ownerships(
    engine: GatewayEngine,
    *,
    downstream: str | None,
    owned_state: dict[str, object] | None,
    owned_only: bool,
) -> list[dict[str, object]]:
    ownerships: list[dict[str, object]] = []
    if owned_state:
        ownerships.append(owned_state)
    if (
        not owned_only
        and downstream
        and (engine.selection_state.upstream is not None or engine.config.uses_wifi)
    ):
        current = engine.policy.ownership(downstream, engine.selection_state.upstream)
        if current not in ownerships:
            ownerships.append(current)
    return ownerships


def _plan_cleanup(
    engine: GatewayEngine,
    *,
    preserve_host_protection: bool,
    owned_only: bool,
) -> CleanupPlan:
    with engine.lock:
        owned_state = engine.lifecycle_state.owned_state
    downstream = _discover_downstream(engine, owned_only=owned_only)
    protected_downstream = _resolve_protected_downstream(
        engine,
        downstream=downstream,
        owned_state=owned_state,
        preserve_host_protection=preserve_host_protection,
    )
    ownerships = _plan_ownerships(
        engine,
        downstream=downstream,
        owned_state=owned_state,
        owned_only=owned_only,
    )
    return CleanupPlan(owned_state, downstream, protected_downstream, ownerships)


def _execute_cleanup(
    engine: GatewayEngine,
    plan: CleanupPlan,
    *,
    preserve_host_protection: bool,
) -> list[str]:
    errors: list[str] = []
    _attempt(errors, "DHCP", engine.dhcp.stop)
    _attempt(
        errors,
        "firewall forwarding",
        lambda: engine.firewall.cleanup(plan.protected_downstream),
    )
    for ownership in plan.ownerships:
        _attempt(
            errors,
            "policy routing",
            partial(engine.policy.cleanup, ownership),
        )
    address_error_count = len(errors)
    _attempt(
        errors,
        "downstream address",
        lambda: engine.downstream.cleanup(plan.owned_state),
    )
    address_cleanup_failed = len(errors) > address_error_count
    if not preserve_host_protection and not address_cleanup_failed:
        _attempt(
            errors,
            "firewall host protection",
            engine.firewall.cleanup,
        )
    return errors


def _reset_after_cleanup(engine: GatewayEngine, errors: list[str]) -> None:
    with engine.lock:
        if not errors:
            engine.lifecycle_state.owned_state = None
        engine.lifecycle_state.applied = False
        engine.selection_state.active_connection = None
        engine.health_state.generation += 1
        engine.health_state.upstream_healthy = False
        engine.health_state.public_ip = None
        engine.health_state.last_health_probe = None
        engine._persist_state()


def cleanup(
    engine: GatewayEngine,
    *,
    preserve_host_protection: bool = False,
    owned_only: bool = False,
) -> None:
    if engine.lifecycle_state.config_error:
        owned_only = True
        preserve_host_protection = False

    with engine.operation_lock:
        plan = _plan_cleanup(
            engine,
            preserve_host_protection=preserve_host_protection,
            owned_only=owned_only,
        )
        errors = _execute_cleanup(
            engine,
            plan,
            preserve_host_protection=preserve_host_protection,
        )
        _reset_after_cleanup(engine, errors)
    if errors:
        raise GatewayError("Cleanup failed: " + "; ".join(errors))
