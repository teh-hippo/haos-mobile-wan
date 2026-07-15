from __future__ import annotations

from dataclasses import dataclass

from .command import RunCommand, run_json
from .config import GatewayConfig
from .upstream_lease import (
    DynamicLease,
    inspect_external_lease,
    load_app_lease,
    validate_dynamic_lease,
)
from .upstream_models import ResolvedUpstream


@dataclass(frozen=True)
class LeaseResolution:
    upstream: ResolvedUpstream | None
    error: str | None
    owner: str | None


def resolved_interface(
    config: GatewayConfig,
    run: RunCommand,
    lease_path,
    interface: str,
) -> LeaseResolution:
    app_lease = load_app_lease(lease_path, interface)
    if app_lease is not None:
        state = external_lease(run, interface)
        if state.addresses != (app_lease[0],):
            if any(
                address != app_lease[0]
                for address in state.addresses
            ):
                return LeaseResolution(
                    None,
                    host_conflict_message(),
                    "external",
                )
            return LeaseResolution(
                None,
                "iPhone USB lease is stale",
                "app",
            )
        if state.has_default_route:
            return LeaseResolution(
                None,
                "iPhone USB lease left a main default route",
                "app",
            )
        upstream, error = validate_dynamic_lease(config, interface, *app_lease)
        return LeaseResolution(upstream, error, "app")
    state = external_lease(run, interface)
    if not state.addresses and not state.has_default_route:
        return LeaseResolution(None, None, None)
    if state.address is None or state.gateway is None:
        return LeaseResolution(None, host_conflict_message(), "external")
    upstream, error = validate_dynamic_lease(
        config,
        interface,
        state.address,
        state.gateway,
    )
    return LeaseResolution(upstream, error, "external")


def host_managed_conflict(
    run: RunCommand,
    lease_path,
    interface: str,
) -> bool:
    state = external_lease(run, interface)
    app_lease = load_app_lease(lease_path, interface)
    if app_lease is not None:
        return (
            any(
                address != app_lease[0]
                for address in state.addresses
            )
            or state.has_default_route
        )
    return bool(state.addresses) or state.has_default_route


def owned_interface(lease_path, runtime_interface: str | None, current: str | None) -> str | None:
    if runtime_interface and load_app_lease(lease_path, runtime_interface):
        return runtime_interface
    if current and load_app_lease(lease_path, current):
        return current
    return None


def external_lease(run: RunCommand, interface: str) -> DynamicLease:
    return inspect_external_lease(
        run_json(
            run,
            "ip",
            "-4",
            "-j",
            "address",
            "show",
            "dev",
            interface,
        ),
        run_json(
            run,
            "ip",
            "-4",
            "-j",
            "route",
            "show",
            "table",
            "main",
            "default",
        ),
        interface,
    )


def host_conflict_message() -> str:
    return (
        "iPhone USB interface is already host-managed; leave ipheth unmanaged "
        "so the app can own DHCP and the main default route"
    )
