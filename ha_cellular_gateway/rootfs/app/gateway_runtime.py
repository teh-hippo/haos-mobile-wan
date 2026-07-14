from __future__ import annotations

import subprocess
import time
from dataclasses import asdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .gateway import GatewayEngine


def refresh_health_if_due(engine: GatewayEngine) -> None:
    with engine.lock:
        last_probe = engine.last_health_probe
        upstream = engine.last_upstream
    now = time.time()
    if last_probe is not None and now - last_probe < engine.HEALTH_PROBE_INTERVAL:
        return
    healthy, public_ip = engine._health_probe(upstream)
    with engine.lock:
        engine.upstream_healthy = healthy
        engine.public_ip = public_ip
        engine.last_health_probe = time.time()


def fail_closed(engine: GatewayEngine, error: Exception) -> None:
    with engine.operation_lock:
        cleanup_error: Exception | None = None
        try:
            engine.cleanup(
                preserve_desired=True,
                preserve_trial_deadline=True,
                preserve_host_protection=engine._protectable_downstream(
                    engine.last_downstream,
                ),
            )
        except (
            engine.gateway_error,
            OSError,
            subprocess.SubprocessError,
            ValueError,
        ) as err:
            cleanup_error = err
        with engine.lock:
            engine.mode = "disabled"
            engine.applied = False
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
        return {
            "mode": engine.mode,
            "desired_mode": engine.desired_mode,
            "configured_mode": engine.config.mode,
            "dry_run": engine.config.dry_run,
            "management_interface": engine.config.management_interface,
            "upstream_mode": engine.config.upstream_mode,
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
            "downstream_present": engine.last_downstream is not None,
            "rules_installed": engine.applied,
            "dnsmasq_running": engine.dhcp.running,
            "upstream_healthy": engine.upstream_healthy,
            "public_ip": engine.public_ip,
            "rollback_armed": engine.trial_deadline is not None,
            "rollback_deadline": engine.trial_deadline,
            "last_reconcile": engine.last_reconcile,
            "last_health_probe": engine.last_health_probe,
            "last_error": engine.last_error,
            "safety_errors": list(engine.last_safety_errors),
            **upstream_status,
            "config": {
                key: value
                for key, value in asdict(engine.config).items()
                if key not in {"dns_servers"}
            },
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
            preserve_trial = (
                engine.desired_mode == "trial" and engine.trial_deadline is not None
            )
            force = bool(engine.owned_state or engine.applied)
        engine.cleanup(
            preserve_desired=True,
            preserve_trial_deadline=preserve_trial,
            force=force,
        )
        engine.upstream.cleanup()
