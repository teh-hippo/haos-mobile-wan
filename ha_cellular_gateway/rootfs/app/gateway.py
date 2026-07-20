from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from .auto_disable import AutoDisable
from .command import CommandRunner
from .config import STATE_PATH, GatewayConfig
from .dhcp import DnsmasqService
from .downstream import DownstreamInterface
from .errors import GatewayError
from .firewall import Firewall
from .gateway_cleanup import cleanup as cleanup_gateway
from .gateway_probe import probe_upstream
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
from .management import ManagementBaseline
from .management_state import (
    resolve_pinned_management,
    restore_management_identity,
)
from .mobile_connection import MobileConnectionResolver
from .networkmanager_wifi import NetworkManagerWifi
from .nm_metadata import WifiProfileMetadata
from .policy import PolicyRouting
from .safety import SafetyInspector
from .state import StateStore
from .upstream_lifecycle import UpstreamLifecycle
from .upstream_models import ResolvedUpstream
from .usb_upstream_factory import build_usb_upstreams


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
        wifi_metadata: WifiProfileMetadata | None = None,
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
        self.upstream, usb_upstreams = build_usb_upstreams(config, self._run)
        self.wifi = NetworkManagerWifi(config, self._run, metadata=wifi_metadata)
        self.connection = MobileConnectionResolver(
            config,
            self.upstream,
            self.wifi,
        )
        self.upstream_lifecycle = UpstreamLifecycle(
            config,
            self.upstream,
            usb_upstreams,
            self.wifi,
        )
        self.config_error = config_error
        self.last_error: str | None = None
        self.last_reconcile: float | None = None
        self.last_health_probe: float | None = None
        self.last_safety_errors = ["Safety checks have not run yet"]
        self.last_downstream: str | None = None
        self.last_upstream: ResolvedUpstream | None = None
        self.active_connection: str | None = None
        self._prev_usb_present = False
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
        management = restore_management_identity(state)
        self.management_interface, management_state_error = management
        self.management_error: str | None = None
        self.auto_disable = AutoDisable(config)
        startup_errors = [
            error
            for error in (
                config_error,
                state_error,
                self.upstream_lifecycle.load_state(state.get("profiles")),
                self.wifi.load_state(state.get("wifi_custody")),
                management_state_error,
            )
            if error
        ]
        owned = state.get("owned")
        self.owned_state = owned if isinstance(owned, dict) else None
        if self.owned_state:
            try:
                self.policy.rule_args(self.owned_state)
                self.policy.route_args(self.owned_state)
            except GatewayError, TypeError, ValueError:
                self.owned_state = None
                startup_errors.append("Persistent ownership state is invalid")
        self.state_load_error = "; ".join(startup_errors) or None
        if self.state_load_error:
            self.last_error = self.state_load_error
        self.upstream_lifecycle.set_persist(self._persist_state)
        self.wifi.set_persist(self._persist_state)

    def _run(
        self, *args: str, check: bool = True, timeout: int = 20
    ) -> subprocess.CompletedProcess[str]:
        return self.runner.run(list(args), check=check, timeout=timeout)

    def _persist_state(self) -> None:
        self.state_store.save(
            owned=self.owned_state,
            profiles=self.upstream_lifecycle.state(),
            wifi_custody=self.wifi.state(),
            management_interface=self.management_interface,
        )

    def cleanup(
        self,
        *,
        preserve_host_protection: bool = False,
        force: bool = False,
        owned_only: bool = False,
    ) -> None:
        cleanup_gateway(
            self,
            preserve_host_protection=preserve_host_protection,
            force=force,
            owned_only=owned_only,
        )

    def _protectable_downstream(self, downstream: str | None) -> bool:
        upstream_interface = (
            self.last_upstream.interface
            if self.last_upstream
            else (self.config.upstream_interface if self.config.uses_wifi else None)
        )
        management_interface = self.management.interface if self.management else None
        return bool(downstream) and downstream not in {
            management_interface,
            upstream_interface,
        }

    def _resolve_management(self) -> ManagementBaseline | None:
        return resolve_pinned_management(self)

    def _resolve_upstream(
        self,
        downstream_interface: str | None = None,
    ) -> tuple[ResolvedUpstream | None, list[str]]:
        resolution = self.connection.resolve(
            self.management,
            downstream_interface,
        )
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

    def _health_probe(
        self, upstream: ResolvedUpstream | None
    ) -> tuple[bool, str | None]:
        return probe_upstream(self, upstream)

    def _refresh_health_if_due(self) -> None:
        refresh_health_if_due(self)

    def apply(self) -> None:
        apply_gateway(self)

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
