from __future__ import annotations

import secrets
import subprocess
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from .command import CommandRunner
from .config import STATE_PATH, TOKEN_PATH, GatewayConfig
from .dhcp import DnsmasqService
from .errors import GatewayError, SafetyError
from .firewall import Firewall
from .policy import PolicyRouting
from .safety import SafetyInspector
from .state import StateStore
from .upstream import IPhoneUsbUpstream, ResolvedUpstream, configured_upstream


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
        with self.lock:
            if self.config.dry_run and not force:
                self.mode = "disabled"
                self.applied = False
                if not preserve_desired:
                    self.desired_mode = "disabled"
                if not preserve_trial_deadline:
                    self.trial_started_at = None
                    self.trial_deadline = None
                self._persist_state()
                return

            downstream = None
            try:
                downstream = self.safety.find_downstream()
            except (GatewayError, OSError, subprocess.SubprocessError, ValueError):
                pass
            preserved_downstream = downstream
            if not self._protectable_downstream(preserved_downstream) and isinstance(self.owned_state, dict):
                candidate = self.owned_state.get("downstream")
                preserved_downstream = candidate if isinstance(candidate, str) else None
            if not preserve_host_protection or not self._protectable_downstream(preserved_downstream):
                preserved_downstream = None
            self.dhcp.stop()
            self.firewall.cleanup(preserved_downstream)

            ownerships: list[dict[str, object]] = []
            if self.owned_state:
                ownerships.append(self.owned_state)
            if downstream:
                current = self.policy.ownership(downstream)
                if current not in ownerships: ownerships.append(current)
            for ownership in ownerships:
                self.policy.cleanup(ownership)

            self.owned_state = None
            self.mode = "disabled"
            self.applied = False
            if not preserve_desired:
                self.desired_mode = "disabled"
            if not preserve_trial_deadline:
                self.trial_started_at = None
                self.trial_deadline = None
            self._persist_state()

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
        with self.lock:
            last_probe = self.last_health_probe
            upstream = self.last_upstream
        now = time.time()
        if last_probe is not None and now - last_probe < self.HEALTH_PROBE_INTERVAL:
            return
        healthy, public_ip = self._health_probe(upstream)
        with self.lock:
            self.upstream_healthy = healthy
            self.public_ip = public_ip
            self.last_health_probe = time.time()

    def apply(self, mode: str, *, recovering: bool = False) -> None:
        if mode not in {"trial", "active"}:
            raise GatewayError("Mode must be trial or active")
        if self.config.dry_run:
            raise SafetyError("Mutation is disabled while dry_run is true")

        with self.lock:
            if not recovering:
                self.desired_mode = mode
                if mode == "trial":
                    self.trial_started_at = time.time()
                    self.trial_deadline = (
                        self.trial_started_at + self.config.trial_seconds
                    )
                else:
                    self.trial_started_at = None
                    self.trial_deadline = None

            downstream = self.safety.find_downstream()
            upstream, upstream_errors = self._resolve_upstream()
            errors = self.safety.errors(
                downstream,
                upstream=upstream,
                upstream_errors=upstream_errors,
                state_error=self.state_load_error,
            )
            self.last_downstream = downstream
            self.last_upstream = upstream
            self.last_safety_errors = errors
            if errors:
                self.cleanup(
                    preserve_desired=True,
                    preserve_trial_deadline=recovering or mode == "trial",
                )
                self.last_error = "; ".join(errors)
                raise SafetyError(self.last_error)
            assert downstream is not None
            assert upstream is not None

            self.cleanup(
                preserve_desired=True,
                preserve_trial_deadline=mode == "trial",
            )
            self.owned_state = self.policy.ownership(downstream, upstream)
            self._persist_state()
            try:
                self.policy.apply(downstream, upstream)
                self.firewall.apply(downstream, upstream.interface)
                self.dhcp.start(downstream)
            except (
                GatewayError,
                OSError,
                subprocess.SubprocessError,
                ValueError,
            ) as err:
                self.cleanup(
                    preserve_desired=True,
                    preserve_trial_deadline=mode == "trial",
                )
                self.last_error = f"Activation failed: {err}"
                raise GatewayError(self.last_error) from err

            self.mode = mode
            self.applied = True
            self.last_error = None
            self._persist_state()

    def reconcile(self, *, refresh_health: bool = False) -> None:
        try:
            with self.lock:
                self.last_reconcile = time.time()
                if self.startup_cleanup_pending:
                    preserve_host_protection = False
                    if self.desired_mode == "disabled" and not self.config.dry_run:
                        candidates: list[str] = []
                        try:
                            downstream = self.safety.find_downstream()
                        except (GatewayError, OSError, subprocess.SubprocessError, ValueError):
                            downstream = None
                        if self._protectable_downstream(downstream):
                            candidates.append(downstream)
                        owned_downstream = self.owned_state.get("downstream") if isinstance(self.owned_state, dict) else None
                        if isinstance(owned_downstream, str) and self._protectable_downstream(owned_downstream) and owned_downstream not in candidates:
                            candidates.append(owned_downstream)
                        preserve_host_protection = bool(
                            candidates and self.firewall.host_guard_chains_installed()
                        )
                    self.cleanup(
                        preserve_desired=True,
                        preserve_trial_deadline=True,
                        preserve_host_protection=preserve_host_protection,
                        force=bool(self.owned_state),
                    )
                    self.state_load_error = None
                    self.startup_cleanup_pending = False
                downstream = self.safety.find_downstream()
                upstream, upstream_errors = self._resolve_upstream()
                try:
                    errors = self.safety.errors(
                        downstream,
                        upstream=upstream,
                        upstream_errors=upstream_errors,
                        state_error=self.state_load_error,
                    )
                except (
                    GatewayError,
                    OSError,
                    subprocess.SubprocessError,
                    ValueError,
                ) as err:
                    errors = [f"Safety inspection failed: {err}"]
                self.last_downstream = downstream
                self.last_upstream = upstream
                self.last_safety_errors = errors

                if (
                    self.desired_mode == "trial"
                    and self.trial_deadline
                    and time.time() >= self.trial_deadline
                ):
                    self.cleanup(preserve_host_protection=True)
                    self.last_error = "Trial expired and was rolled back"
                    return

                if self.desired_mode not in {"trial", "active"}:
                    if self.owned_state or self.applied or self.dhcp.running:
                        self.cleanup(
                            preserve_host_protection=self._protectable_downstream(
                                downstream
                            ),
                            force=bool(self.owned_state or self.applied),
                        )
                    elif (
                        not self.config.dry_run
                        and self._protectable_downstream(downstream)
                        and not self.firewall.host_protection_installed(downstream)
                    ):
                        self.firewall.protect_host(downstream)
                    return

                if errors:
                    self.cleanup(
                        preserve_desired=True,
                        preserve_trial_deadline=True,
                        preserve_host_protection=self._protectable_downstream(
                            downstream
                        ),
                    )
                    self.last_error = "; ".join(errors)
                    return

                if (
                    self.mode != self.desired_mode
                    or not self.policy.installed(downstream, upstream)
                    or not self.firewall.installed(
                        downstream,
                        upstream.interface if upstream else None,
                    )
                    or not self.dhcp.running
                ):
                    self.apply(self.desired_mode, recovering=True)
        finally:
            if refresh_health:
                self._refresh_health_if_due()

    def _fail_closed(self, error: Exception) -> None:
        cleanup_error: Exception | None = None
        try:
            self.cleanup(
                preserve_desired=True,
                preserve_trial_deadline=True,
                preserve_host_protection=self._protectable_downstream(
                    self.last_downstream,
                ),
            )
        except (
            GatewayError,
            OSError,
            subprocess.SubprocessError,
            ValueError,
        ) as err:
            cleanup_error = err
        with self.lock:
            self.mode = "disabled"
            self.applied = False
            self.last_error = (
                f"{error}; cleanup failed: {cleanup_error}"
                if cleanup_error
                else str(error)
            )
            self.last_safety_errors = [self.last_error]

    def status(self) -> dict[str, object]:
        with self.lock:
            upstream = self.last_upstream
            upstream_status = self.upstream.runtime_status()
            return {
                "mode": self.mode,
                "desired_mode": self.desired_mode,
                "configured_mode": self.config.mode,
                "dry_run": self.config.dry_run,
                "management_interface": self.config.management_interface,
                "upstream_mode": self.config.upstream_mode,
                "configured_upstream_interface": self.config.upstream_interface,
                "upstream_interface": (
                    upstream.interface
                    if upstream
                    else upstream_status["upstream_runtime_interface"]
                    or self.config.upstream_interface
                ),
                "upstream_address": upstream.address if upstream else None,
                "upstream_gateway": upstream.gateway if upstream else None,
                "downstream_interface": self.last_downstream,
                "downstream_present": self.last_downstream is not None,
                "rules_installed": self.applied,
                "dnsmasq_running": self.dhcp.running,
                "upstream_healthy": self.upstream_healthy,
                "public_ip": self.public_ip,
                "rollback_armed": self.trial_deadline is not None,
                "rollback_deadline": self.trial_deadline,
                "last_reconcile": self.last_reconcile,
                "last_health_probe": self.last_health_probe,
                "last_error": self.last_error,
                "safety_errors": list(self.last_safety_errors),
                **upstream_status,
                "config": {
                    key: value
                    for key, value in asdict(self.config).items()
                    if key not in {"dns_servers"}
                },
            }

    def health(self) -> dict[str, object]:
        with self.lock:
            last_activity = self.last_reconcile or self.started_at
            maximum_age = max(30, self.config.reconcile_seconds * 3)
            return {"ok": time.time() - last_activity <= maximum_age, "last_reconcile": self.last_reconcile}

    def run_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.reconcile(refresh_health=True)
            except (
                GatewayError,
                OSError,
                subprocess.SubprocessError,
                ValueError,
            ) as err:
                self._fail_closed(err)
            if self.stop_event.wait(self.config.reconcile_seconds):
                break

    def stop(self) -> None:
        self.stop_event.set()
        preserve_trial = self.desired_mode == "trial" and self.trial_deadline is not None
        self.cleanup(
            preserve_desired=True,
            preserve_trial_deadline=preserve_trial,
            force=bool(self.owned_state or self.applied),
        )
        self.upstream.cleanup()


def load_or_create_token(path: Path = TOKEN_PATH) -> str:
    if path.exists():
        path.chmod(0o600)
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token := secrets.token_urlsafe(32), encoding="utf-8")
    path.chmod(0o600)
    return token
