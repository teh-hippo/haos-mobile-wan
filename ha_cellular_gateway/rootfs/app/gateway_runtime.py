from __future__ import annotations

import subprocess
import time
from typing import TYPE_CHECKING

from .status_issues import build_status_issues

if TYPE_CHECKING:
    from .gateway import GatewayEngine


def refresh_health_if_due(engine: GatewayEngine) -> None:
    with engine.lock:
        last_probe = engine.last_health_probe
        upstream = engine.last_upstream
        generation = engine.health_generation
    now = time.time()
    if last_probe is not None and now - last_probe < engine.HEALTH_PROBE_INTERVAL:
        return
    healthy, public_ip = engine._health_probe(upstream)
    with engine.lock:
        if (
            engine.last_upstream != upstream
            or engine.health_generation != generation
        ):
            return
        engine.upstream_healthy = healthy
        engine.public_ip = public_ip
        engine.last_health_probe = time.time()


def fail_closed(engine: GatewayEngine, error: Exception) -> None:
    with engine.operation_lock:
        cleanup_error: Exception | None = None
        try:
            engine.cleanup(
                preserve_enabled=True,
                preserve_host_protection=True,
            )
        except (
            engine.gateway_error,
            OSError,
            subprocess.SubprocessError,
            ValueError,
        ) as err:
            cleanup_error = err
        with engine.lock:
            engine.applied = False
            engine.active_connection = None
            engine.last_error = (
                f"{error}; cleanup failed: {cleanup_error}"
                if cleanup_error
                else str(error)
            )
            engine.last_safety_errors = [engine.last_error]


def status(engine: GatewayEngine) -> dict[str, object]:
    with engine.lock:
        upstream = engine.last_upstream
        upstream_status = engine.upstream.runtime_status()
        issues = build_status_issues(
            engine.last_safety_errors,
            engine.last_error,
            upstream_status,
            engine.connection_warnings,
        )
        return {
            "enabled": engine.enabled,
            "configured_enabled": engine.config.enabled,
            "active": engine.applied,
            "management_interface": engine.config.management_interface,
            "mobile_connection": engine.config.mobile_connection,
            "active_connection": engine.active_connection,
            "fallback_active": engine.applied and engine.fallback_selected,
            "fallback_reason": engine.fallback_reason,
            "connection_warnings": list(engine.connection_warnings),
            "configured_upstream_interface": engine.config.upstream_interface,
            "upstream_interface": (
                upstream.interface
                if upstream
                else upstream_status["upstream_runtime_interface"]
                or engine.config.upstream_interface
            ),
            "upstream_address": upstream.address if upstream else None,
            "upstream_gateway": upstream.gateway if upstream else None,
            "downstream_interface": engine.last_downstream,
            "downstream_mac": engine.downstream.mac(engine.last_downstream)
            if engine.last_downstream
            else None,
            "downstream_present": engine.last_downstream is not None,
            "rules_installed": engine.applied,
            "dnsmasq_running": engine.dhcp.running,
            "upstream_healthy": engine.upstream_healthy,
            "public_ip": engine.public_ip,
            "last_reconcile": engine.last_reconcile,
            "last_health_probe": engine.last_health_probe,
            "last_error": engine.last_error,
            "safety_errors": list(engine.last_safety_errors),
            "issues": issues,
            **upstream_status,
            "config": _status_config(engine),
        }


def health(engine: GatewayEngine) -> dict[str, object]:
    with engine.lock:
        last_activity = engine.last_reconcile or engine.started_at
        maximum_age = max(30, engine.config.reconcile_seconds * 3)
        return {
            "ok": time.time() - last_activity <= maximum_age,
            "last_reconcile": engine.last_reconcile,
        }


def run_loop(engine: GatewayEngine) -> None:
    while not engine.stop_event.is_set():
        try:
            engine.reconcile(refresh_health=True)
        except (
            engine.gateway_error,
            OSError,
            subprocess.SubprocessError,
            ValueError,
        ) as err:
            engine._fail_closed(err)
        if engine.stop_event.wait(engine.config.reconcile_seconds):
            break


def stop(engine: GatewayEngine) -> None:
    with engine.operation_lock:
        engine.stop_event.set()
        with engine.lock:
            force = bool(engine.owned_state or engine.applied)
        cleanup_error: Exception | None = None
        try:
            engine.cleanup(
                preserve_enabled=True,
                force=force,
            )
        except (
            engine.gateway_error,
            OSError,
            subprocess.SubprocessError,
            ValueError,
        ) as err:
            cleanup_error = err
        try:
            engine.upstream.cleanup()
        except (
            engine.gateway_error,
            OSError,
            subprocess.SubprocessError,
            ValueError,
        ) as err:
            if cleanup_error:
                raise engine.gateway_error(
                    f"{cleanup_error}; upstream cleanup failed: {err}"
                ) from err
            raise
        if cleanup_error:
            raise cleanup_error


def _status_config(engine: GatewayEngine) -> dict[str, object]:
    config = engine.config
    return {
        "enabled": config.enabled,
        "management_interface": config.management_interface,
        "management_address": config.management_address,
        "mobile_connection": config.mobile_connection,
        "upstream_interface": config.upstream_interface,
        "upstream_address": config.upstream_address,
        "upstream_gateway": config.upstream_gateway,
        "hotspot_ssid": config.hotspot_ssid,
        "downstream_mac": config.downstream_mac,
        "downstream_address": config.downstream_address,
    }
