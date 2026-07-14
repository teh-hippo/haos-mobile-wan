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
from .gateway_reconcile import (
    apply as apply_gateway,
    cleanup as cleanup_gateway,
    reconcile as reconcile_gateway,
)
from .gateway_runtime import (
    fail_closed,
    health,
    refresh_health_if_due,
    run_loop,
    status,
    stop,
)
from .policy import PolicyRouting
from .safety import SafetyInspector
from .state import StateStore
from .upstream_iphone import IPhoneUsbUpstream
from .upstream_models import ResolvedUpstream, configured_upstream


class GatewayEngine:
    HEALTH_PROBE_INTERVAL = 300

    def __init__(
        self,
        config: GatewayConfig,
        *,
        runner: CommandRunner | None = None,
        read_text: Callable[[Path], str] | None = None,
        state_path: Path | None = None,
    ) -> None:
        self.config = config
        self.runner = runner or CommandRunner()
        self.read_text = read_text or (lambda path: path.read_text(encoding="utf-8"))
        self.lock = threading.RLock()
        self.operation_lock = threading.RLock()
        self.firewall = Firewall(config, self._run)
        self.policy = PolicyRouting(config, self._run)
        self.safety = SafetyInspector(
            config,
            self._run,
            self.read_text,
            self.firewall,
            self.policy,
        )
        self.state_store = StateStore(state_path or STATE_PATH)
        self.upstream = IPhoneUsbUpstream(config, self._run)

        self.mode = "disabled"
        self.desired_mode = config.mode if config.mode in {"trial", "active"} else "disabled"
        self.last_error: str | None = None
        self.last_reconcile: float | None = None
        self.last_health_probe: float | None = None
        self.last_safety_errors = ["Safety checks have not run yet"]
        self.last_downstream: str | None = None
        self.last_upstream: ResolvedUpstream | None = None
        self.upstream_healthy = False
        self.public_ip: str | None = None
        self.dhcp = DnsmasqService(config, self._run)
        self.stop_event = threading.Event()
        self.applied = False
        self.started_at = time.time()
        self.startup_cleanup_pending = True
        self.gateway_error = GatewayError

        state, state_error = self.state_store.load()
        self.state_load_error = state_error
        owned = state.get("owned")
        self.owned_state = owned if isinstance(owned, dict) else None
        if self.owned_state:
            try:
                self.policy.rule_args(self.owned_state)
                self.policy.route_args(self.owned_state)
            except (GatewayError, TypeError, ValueError):
                self.owned_state = None
                self.state_load_error = "Persistent ownership state is invalid"
                self.desired_mode = "disabled"
        self.trial_started_at: float | None = None
        self.trial_deadline: float | None = None
        trial = state.get("trial")
        if self.desired_mode == "trial" and isinstance(trial, dict):
            try:
                started_at = float(trial["started_at"])
                deadline = float(trial["deadline"])
                now = time.time()
                if (
                    deadline < started_at
                    or deadline > started_at + self.config.trial_seconds + 5
                    or now + 60 < started_at
                ):
                    raise ValueError("trial timestamps are inconsistent")
                self.trial_started_at = started_at
                self.trial_deadline = deadline
            except (KeyError, TypeError, ValueError):
                self.state_load_error = "Persistent trial state is invalid"
                self.desired_mode = "disabled"
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
        self.state_store.save(owned=self.owned_state, trial_started_at=self.trial_started_at, trial_deadline=self.trial_deadline)

    def cleanup(
        self,
        *,
        preserve_desired: bool = False,
        preserve_trial_deadline: bool = False,
        preserve_host_protection: bool = False,
        force: bool = False,
    ) -> None:
        cleanup_gateway(
            self,
            preserve_desired=preserve_desired,
            preserve_trial_deadline=preserve_trial_deadline,
            preserve_host_protection=preserve_host_protection,
            force=force,
        )

    def _protectable_downstream(self, downstream: str | None) -> bool:
        return bool(downstream) and downstream not in {
            self.config.management_interface,
            self.config.upstream_interface,
        }

    def _resolve_upstream(self) -> tuple[ResolvedUpstream | None, list[str]]:
        if self.config.upstream_mode == "iphone_usb":
            return self.upstream.resolve(allow_mutation=not self.config.dry_run)
        return configured_upstream(self.config), []

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

    def apply(self, mode: str, *, recovering: bool = False) -> None:
        apply_gateway(self, mode, recovering=recovering)

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
