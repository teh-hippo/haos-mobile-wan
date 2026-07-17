from __future__ import annotations

import secrets
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from .command import CommandRunner
from .config import STATE_PATH, TOKEN_PATH, GatewayConfig
from .dhcp import DnsmasqService
from .errors import GatewayError
from .firewall import Firewall
from .gateway_cleanup import cleanup as cleanup_gateway
from .gateway_reconcile import apply as apply_gateway
from .gateway_reconcile import reconcile as reconcile_gateway
from .gateway_runtime import (
    fail_closed,
    health,
    refresh_health_if_due,
    run_loop,
    status,
    stop,
)
from .hotspot import interface_status
from .downstream import DownstreamInterface
from .management import ManagementBaseline, resolve_management
from .mobile_connection import MobileConnectionResolver
from .policy import PolicyRouting
from .safety import SafetyInspector
from .state import StateStore
from .upstream_iphone import IPhoneUsbUpstream
from .upstream_models import ResolvedUpstream


class GatewayEngine:
    HEALTH_PROBE_INTERVAL = 300

    def __init__(
        self,
        config: GatewayConfig,
        *,
        runner: CommandRunner | None = None,
        read_text: Callable[[Path], str] | None = None,
        state_path: Path | None = None,
        config_error: str | None = None,
        hotspot_error: str | None = None,
    ) -> None:
        self.config = config
        self.management: ManagementBaseline | None = None
        self.runner = runner or CommandRunner()
        self.read_text = read_text or (lambda path: path.read_text(encoding="utf-8"))
        self.lock = threading.RLock()
        self.operation_lock = threading.RLock()
        self.firewall = Firewall(config, self._run)
        self.policy = PolicyRouting(config, self._run)
        self.downstream = DownstreamInterface(
            config,
            self._run,
            self.read_text,
        )
        self.safety = SafetyInspector(
            config,
            self._run,
            self.read_text,
            self.firewall,
            self.policy,
            self.downstream,
        )
        self.state_store = StateStore(state_path or STATE_PATH)
        self.upstream = IPhoneUsbUpstream(config, self._run)
        self.connection = MobileConnectionResolver(
            config,
            self.upstream,
            wifi_error=hotspot_error,
        )

        self.config_error = config_error
        self.enabled = config.enabled and not config_error
        self.last_error: str | None = None
        self.last_reconcile: float | None = None
        self.last_health_probe: float | None = None
        self.last_safety_errors = ["Safety checks have not run yet"]
        self.last_downstream: str | None = None
        self.last_upstream: ResolvedUpstream | None = None
        self.active_connection: str | None = None
        self._prev_iphone_present = False
        self._prev_wifi_connected = False
        self.health_generation = 0
        self.connection_warnings: list[str] = []
        self.fallback_selected = False
        self.fallback_reason: str | None = None
        self.upstream_healthy = False
        self.public_ip: str | None = None
        self.dhcp = DnsmasqService(config, self._run)
        self.stop_event = threading.Event()
        self.applied = False
        self.started_at = time.time()
        self.startup_cleanup_pending = True
        self.gateway_error = GatewayError

        state, state_error = self.state_store.load()
        startup_errors = [
            error for error in (config_error, state_error) if error
        ]
        owned = state.get("owned")
        self.owned_state = owned if isinstance(owned, dict) else None
        if self.owned_state:
            try:
                self.policy.rule_args(self.owned_state)
                self.policy.route_args(self.owned_state)
            except (GatewayError, TypeError, ValueError):
                self.owned_state = None
                startup_errors.append("Persistent ownership state is invalid")
                self.enabled = False
        self.state_load_error = "; ".join(startup_errors) or None
        if self.state_load_error:
            self.last_error = self.state_load_error

    def _run(
        self,
        *args: str,
        check: bool = True,
        timeout: int = 20,
    ) -> subprocess.CompletedProcess[str]:
        return self.runner.run(list(args), check=check, timeout=timeout)

    def _persist_state(self) -> None:
        self.state_store.save(owned=self.owned_state)

    def cleanup(
        self,
        *,
        preserve_enabled: bool = False,
        preserve_host_protection: bool = False,
        force: bool = False,
        owned_only: bool = False,
    ) -> None:
        cleanup_gateway(
            self,
            preserve_enabled=preserve_enabled,
            preserve_host_protection=preserve_host_protection,
            force=force,
            owned_only=owned_only,
        )

    def _protectable_downstream(self, downstream: str | None) -> bool:
        upstream_interface = (
            self.last_upstream.interface
            if self.last_upstream
            else self.config.upstream_interface
        )
        management_interface = (
            self.management.interface if self.management else None
        )
        return bool(downstream) and downstream not in {
            management_interface,
            upstream_interface,
        }

    def _resolve_management(self) -> ManagementBaseline | None:
        baseline = resolve_management(self._run)
        with self.lock:
            self.management = baseline
        return baseline

    def _resolve_upstream(self) -> tuple[ResolvedUpstream | None, list[str]]:
        resolution = self.connection.resolve(self.management)
        with self.lock:
            self.connection_warnings = list(resolution.warnings)
            self.fallback_selected = resolution.fallback_active
            self.fallback_reason = resolution.fallback_reason
        return resolution.upstream, list(resolution.errors)

    def _record_upstream(self, upstream: ResolvedUpstream | None) -> None:
        with self.lock:
            if upstream != self.last_upstream:
                self.health_generation += 1
                self.upstream_healthy = False
                self.public_ip = None
                self.last_health_probe = None
            self.last_upstream = upstream

    def _interface_status(self) -> dict[str, object] | None:
        return interface_status(self.config)

    def _health_probe(self, upstream: ResolvedUpstream | None) -> tuple[bool, str | None]:
        if upstream is None:
            return False, None
        try:
            result = self._run(
                "curl",
                "-4",
                "-fsS",
                "--interface",
                upstream.ip,
                "--max-time",
                "10",
                "https://www.cloudflare.com/cdn-cgi/trace",
                check=False,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return False, None
        if result.returncode != 0:
            return False, None
        public_ip = None
        for line in result.stdout.splitlines():
            if line.startswith("ip="):
                public_ip = line.partition("=")[2]
                break
        return True, public_ip

    def _refresh_health_if_due(self) -> None:
        refresh_health_if_due(self)

    def apply(self, *, recovering: bool = False) -> None:
        apply_gateway(self, recovering=recovering)

    def reconcile(self, *, refresh_health: bool = False) -> None:
        reconcile_gateway(self, refresh_health=refresh_health)

    def _fail_closed(self, error: Exception) -> None:
        fail_closed(self, error)

    def status(self) -> dict[str, object]:
        return status(self)

    def health(self) -> dict[str, object]:
        return health(self)

    def run_loop(self) -> None:
        run_loop(self)

    def stop(self) -> None:
        stop(self)


def load_or_create_token(path: Path = TOKEN_PATH) -> str:
    if path.exists():
        path.chmod(0o600)
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token := secrets.token_urlsafe(32), encoding="utf-8")
    path.chmod(0o600)
    return token
