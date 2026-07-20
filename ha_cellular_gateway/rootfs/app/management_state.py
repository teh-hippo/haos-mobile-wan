from __future__ import annotations

from typing import TYPE_CHECKING

from .management import ManagementBaseline, resolve_management

if TYPE_CHECKING:
    from .gateway import GatewayEngine


def restore_management_identity(
    state: dict[str, object],
) -> tuple[str | None, str | None]:
    interface = state.get("management_interface")
    if interface is None:
        return None, None
    if not isinstance(interface, str):
        return None, "Persistent management identity is invalid"
    return interface, None


def resolve_pinned_management(
    engine: GatewayEngine,
) -> ManagementBaseline | None:
    baseline = resolve_management(engine._run)
    error = None
    pinned_interface = engine.lifecycle_state.management_interface
    if (
        baseline is not None
        and pinned_interface is not None
        and baseline.interface != pinned_interface
    ):
        error = (
            f"Management interface changed from {pinned_interface} "
            f"to {baseline.interface}"
        )
        baseline = None
    elif baseline is not None and pinned_interface is None:
        engine.lifecycle_state.management_interface = baseline.interface
        engine._persist_state()
    with engine.lock:
        engine.management = baseline
        engine.lifecycle_state.management_error = error
    return baseline
