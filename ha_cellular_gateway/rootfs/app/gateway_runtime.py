from __future__ import annotations

import logging
import subprocess
import time
from typing import TYPE_CHECKING

from .status_issues import build_status_issues
from .status_model import derive_gateway_state, derive_health

if TYPE_CHECKING:
    from .gateway import GatewayEngine

_LOGGER = logging.getLogger(__name__)


def refresh_health_if_due(engine: GatewayEngine) -> None:
    with engine.lock:
        applied = engine.lifecycle_state.applied
        last_probe = engine.health_state.last_health_probe
        upstream = engine.selection_state.upstream
        generation = engine.health_state.generation
    if not applied or upstream is None:
        with engine.lock:
            engine.health_state.upstream_healthy = False
            engine.health_state.public_ip = None
            engine.health_state.last_health_probe = None
        return
    now = time.time()
    if last_probe is not None and now - last_probe < engine.HEALTH_PROBE_INTERVAL:
        return
    healthy, public_ip = engine._health_probe(upstream)
    with engine.lock:
        if (
            engine.selection_state.upstream != upstream
            or engine.health_state.generation != generation
        ):
            return
        engine.health_state.upstream_healthy = healthy
        engine.health_state.public_ip = public_ip
        engine.health_state.last_health_probe = time.time()


def fail_closed(engine: GatewayEngine, error: Exception) -> None:
    with engine.operation_lock:
        cleanup_error: Exception | None = None
        try:
            engine.cleanup(
                preserve_host_protection=True,
            )
        except (
            engine.gateway_error,
            OSError,
            subprocess.SubprocessError,
            ValueError,
        ) as err:
            cleanup_error = err
        engine.upstream_lifecycle.deactivate(engine.management)
        engine._persist_state()
        lifecycle_error = engine.upstream_lifecycle.error
        with engine.lock:
            engine.lifecycle_state.applied = False
            engine.selection_state.active_connection = None
            engine.lifecycle_state.last_error = (
                f"{error}; cleanup failed: {cleanup_error}"
                if cleanup_error
                else str(error)
            )
            if lifecycle_error:
                engine.lifecycle_state.last_error += f"; {lifecycle_error}"
            engine.selection_state.safety_errors = [engine.lifecycle_state.last_error]


def status(engine: GatewayEngine) -> dict[str, object]:
    with engine.lock:
        upstream = engine.selection_state.upstream
        upstream_status = engine.upstream.runtime_status()
        issues = build_status_issues(
            engine.selection_state.safety_errors,
            engine.lifecycle_state.last_error,
            upstream_status,
            engine.selection_state.warnings,
            [
                error
                for error in (
                    engine.auto_disable.error,
                    engine.upstream_lifecycle.error,
                )
                if error
            ],
        )
        health_state, health_issues = derive_health(issues)
        downstream = engine.selection_state.downstream
        return {
            "state": derive_gateway_state(
                engine.lifecycle_state.applied,
                issues,
            ),
            "health": health_state,
            "health_issues": health_issues,
            "active": engine.lifecycle_state.applied,
            "management_interface": (
                engine.management.interface if engine.management else None
            ),
            "mobile_connection": engine.config.mobile_connection,
            "active_connection": engine.selection_state.active_connection,
            "fallback_active": (
                engine.lifecycle_state.applied
                and engine.selection_state.fallback_selected
            ),
            "fallback_reason": engine.selection_state.fallback_reason,
            "connection_warnings": list(engine.selection_state.warnings),
            "configured_upstream_interface": engine.config.upstream_interface,
            "upstream_interface": (
                upstream.interface
                if upstream
                else upstream_status["upstream_runtime_interface"]
                or engine.config.upstream_interface
            ),
            "upstream_address": upstream.address if upstream else None,
            "upstream_gateway": upstream.gateway if upstream else None,
            "downstream_interface": downstream,
            "downstream_mac": (
                engine.downstream.mac(downstream) if downstream else None
            ),
            "downstream_present": downstream is not None,
            "rules_installed": engine.lifecycle_state.applied,
            "dnsmasq_running": engine.dhcp.running,
            "upstream_healthy": engine.health_state.upstream_healthy,
            "public_ip": engine.health_state.public_ip,
            "auto_disable_at": engine.auto_disable.deadline_iso,
            "last_reconcile": engine.lifecycle_state.last_reconcile,
            "last_health_probe": engine.health_state.last_health_probe,
            "last_error": engine.lifecycle_state.last_error,
            "safety_errors": list(engine.selection_state.safety_errors),
            "issues": issues,
            "networkmanager": engine.upstream_lifecycle.diagnostics(),
            **upstream_status,
            "config": _status_config(engine),
        }


def health(engine: GatewayEngine) -> dict[str, object]:
    with engine.lock:
        last_activity = (
            engine.lifecycle_state.last_reconcile or engine.lifecycle_state.started_at
        )
        maximum_age = max(30, engine.config.reconcile_seconds * 3)
        return {
            "ok": time.time() - last_activity <= maximum_age,
            "last_reconcile": engine.lifecycle_state.last_reconcile,
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
        if engine.stop_event.is_set():
            break
        engine.auto_disable.reconcile(engine)
        if engine.stop_event.wait(engine.config.reconcile_seconds):
            break


def stop(engine: GatewayEngine) -> None:
    started = time.monotonic()
    _LOGGER.info("Graceful shutdown cleanup started")
    engine.stop_event.set()
    with engine.operation_lock:
        cleanup_error: Exception | None = None
        try:
            engine.cleanup()
        except (
            engine.gateway_error,
            OSError,
            subprocess.SubprocessError,
            ValueError,
        ) as err:
            cleanup_error = err
        engine.upstream_lifecycle.deactivate(engine.management)
        engine._persist_state()
        lifecycle_error = engine.upstream_lifecycle.error
        if lifecycle_error:
            message = (
                f"{cleanup_error}; {lifecycle_error}"
                if cleanup_error
                else lifecycle_error
            )
            _LOGGER.error(
                "Graceful shutdown cleanup failed after %.1f seconds: %s",
                time.monotonic() - started,
                message,
            )
            if cleanup_error:
                raise engine.gateway_error(message)
            raise engine.gateway_error(lifecycle_error)
        if cleanup_error:
            _LOGGER.error(
                "Graceful shutdown cleanup failed after %.1f seconds: %s",
                time.monotonic() - started,
                cleanup_error,
            )
            raise cleanup_error
    _LOGGER.info(
        "Graceful shutdown cleanup completed in %.1f seconds",
        time.monotonic() - started,
    )


def _status_config(engine: GatewayEngine) -> dict[str, object]:
    config = engine.config
    management = engine.management
    return {
        "auto_disable_minutes": config.auto_disable_minutes,
        "management_interface": management.interface if management else None,
        "management_address": management.address if management else None,
        "mobile_connection": config.mobile_connection,
        "upstream_interface": config.upstream_interface,
        "upstream_address": config.upstream_address,
        "upstream_gateway": config.upstream_gateway,
        "hotspot_ssid": config.hotspot_ssid,
        "downstream_mac": config.downstream_mac,
        "downstream_address": config.downstream_address,
    }
