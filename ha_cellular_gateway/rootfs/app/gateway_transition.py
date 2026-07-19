from __future__ import annotations

from typing import TYPE_CHECKING

from .gateway_cleanup import cleanup

if TYPE_CHECKING:
    from .gateway import GatewayEngine
    from .upstream_models import ResolvedUpstream


def cleanup_changed_ownership(
    engine: GatewayEngine,
    downstream: str | None,
    upstream: ResolvedUpstream | None,
) -> None:
    if (
        downstream is None
        or upstream is None
        or not engine.owned_state
    ):
        return
    expected = engine.policy.ownership(downstream, upstream)
    if all(
        engine.owned_state.get(key) == expected[key]
        for key in (
            "downstream",
            "upstream_interface",
            "upstream_address",
            "upstream_gateway",
        )
    ):
        return
    cleanup(
        engine,
        preserve_host_protection=True,
    )
