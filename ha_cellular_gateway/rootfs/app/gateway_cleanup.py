from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import TYPE_CHECKING

from .errors import GatewayError

if TYPE_CHECKING:
    from .gateway import GatewayEngine

OPERATION_ERRORS = (GatewayError, OSError, subprocess.SubprocessError, ValueError)


def _attempt(
    errors: list[str],
    label: str,
    action: Callable[[], None],
) -> None:
    try:
        action()
    except OPERATION_ERRORS as err:
        errors.append(f"{label}: {err}")


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
        protected_downstream = downstream
        if (
            not engine._protectable_downstream(protected_downstream)
            and isinstance(owned_state, dict)
        ):
            candidate = owned_state.get("downstream")
            protected_downstream = candidate if isinstance(candidate, str) else None
        if (
            not (
                preserve_host_protection
                or engine.downstream.owns_address(owned_state)
            )
            or not engine._protectable_downstream(protected_downstream)
        ):
            protected_downstream = None

        errors: list[str] = []
        _attempt(errors, "DHCP", engine.dhcp.stop)
        _attempt(
            errors,
            "firewall forwarding",
            lambda: engine.firewall.cleanup(protected_downstream),
        )

        ownerships: list[dict[str, object]] = []
        if owned_state:
            ownerships.append(owned_state)
        if downstream:
            current = engine.policy.ownership(downstream)
            if current not in ownerships:
                ownerships.append(current)
        for ownership in ownerships:
            _attempt(
                errors,
                "policy routing",
                lambda ownership=ownership: engine.policy.cleanup(ownership),
            )
        address_error_count = len(errors)
        _attempt(
            errors,
            "downstream address",
            lambda: engine.downstream.cleanup(owned_state),
        )
        address_cleanup_failed = len(errors) > address_error_count
        if not preserve_host_protection and not address_cleanup_failed:
            _attempt(
                errors,
                "firewall host protection",
                engine.firewall.cleanup,
            )

        with engine.lock:
            if not errors:
                engine.owned_state = None
            engine.mode = "disabled"
            engine.applied = False
            if not preserve_desired:
                engine.desired_mode = "disabled"
            if not preserve_trial_deadline:
                engine.trial_started_at = None
                engine.trial_deadline = None
            engine._persist_state()
        if errors:
            raise GatewayError("Cleanup failed: " + "; ".join(errors))
