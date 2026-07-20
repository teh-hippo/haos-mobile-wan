from __future__ import annotations

import time
from dataclasses import dataclass, field

from .upstream_models import ResolvedUpstream


@dataclass
class LifecycleState:
    """Startup, persisted-ownership, and outcome state for the reconcile loop."""

    config_error: str | None = None
    state_load_error: str | None = None
    management_interface: str | None = None
    management_error: str | None = None
    owned_state: dict[str, object] | None = None
    startup_cleanup_pending: bool = True
    applied: bool = False
    started_at: float = field(default_factory=time.time)
    last_reconcile: float | None = None
    last_error: str | None = None


@dataclass
class SelectionState:
    """The most recently resolved downstream/upstream connection pairing."""

    downstream: str | None = None
    upstream: ResolvedUpstream | None = None
    active_connection: str | None = None
    safety_errors: list[str] = field(
        default_factory=lambda: ["Safety checks have not run yet"]
    )
    warnings: list[str] = field(default_factory=list)
    fallback_selected: bool = False
    fallback_reason: str | None = None
    prev_usb_present: bool = False
    prev_wifi_connected: bool = False


@dataclass
class HealthState:
    """Upstream reachability probe results and their invalidation generation."""

    generation: int = 0
    upstream_healthy: bool = False
    public_ip: str | None = None
    last_health_probe: float | None = None
