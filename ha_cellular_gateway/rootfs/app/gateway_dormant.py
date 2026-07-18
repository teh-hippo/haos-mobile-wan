from __future__ import annotations

from typing import TYPE_CHECKING

from .gateway_cleanup import cleanup

if TYPE_CHECKING:
    from .gateway import GatewayEngine
    from .management import ManagementBaseline


def reconcile_disabled(
    engine: GatewayEngine,
    downstream: str | None,
    management: ManagementBaseline | None,
) -> None:
    engine.upstream_lifecycle.deactivate(management)
    engine._persist_state()
    engine.connection.wifi_error = None
    with engine.lock:
        engine.last_downstream = downstream
        engine.last_safety_errors = (
            [engine.upstream_lifecycle.error]
            if engine.upstream_lifecycle.error
            else []
        )
        engine.last_error = engine.upstream_lifecycle.error
    engine._record_upstream(None)

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
    if (
        engine._protectable_downstream(downstream)
        and not engine.firewall.host_protection_installed(downstream)
    ):
        assert downstream is not None
        engine.firewall.protect_host(downstream)
