from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .fault_catalogue_host import HOST_FAULTS
from .fault_catalogue_rules import RULE_FAULTS
from .fault_catalogue_upstream import PAIRING_FAULTS, UPSTREAM_FAULTS
from .faults import (
    DRIVER_INACTIVE,
    DRIVER_INACTIVE_MARKER,
    GENERIC,
    PLACEHOLDER_ERROR,
    Fault,
)

# Faults that spell themselves out in full are searched before those matched by
# a head, so a broader entry never captures a fault that names itself exactly.
FAULTS = (*HOST_FAULTS, *UPSTREAM_FAULTS, *RULE_FAULTS)


def classify(error: str) -> Fault:
    for spec in FAULTS:
        if spec.matches(error):
            return spec.issue(error)
    return GENERIC.issue(error)


def build_status_issues(
    safety_errors: Iterable[str],
    last_error: str | None,
    upstream_status: dict[str, Any],
    connection_warnings: Iterable[str] = (),
    runtime_errors: Iterable[str] = (),
) -> list[dict[str, Any]]:
    reported = list(safety_errors)
    collector = _Collector()

    upstream = _upstream_fault(upstream_status)
    suppressed: str | None = None
    if upstream is not None:
        collector.add(upstream)
        suppressed = _pairing_message(upstream_status)

    for error in reported:
        if error not in (PLACEHOLDER_ERROR, suppressed):
            collector.add(classify(error))

    for warning in connection_warnings:
        fault = classify(warning)
        if fault.spec is not GENERIC:
            collector.add(fault, blocking=False)

    if last_error and not reported:
        collector.add(classify(last_error))

    for error in runtime_errors:
        collector.add(classify(error))

    return collector.issues


class _Collector:
    def __init__(self) -> None:
        self.issues: list[dict[str, Any]] = []
        self._seen: set[str] = set()

    def add(self, fault: Fault, *, blocking: bool = True) -> None:
        spec = fault.spec
        if spec.id in self._seen:
            return
        self._seen.add(spec.id)
        self.issues.append(
            {
                "id": spec.id,
                "translation_key": spec.translation_key,
                "repairable": bool(spec.translation_key) and not spec.transient,
                "transient": spec.transient,
                "blocking": blocking,
                "message": fault.message,
            }
        )


def _pairing_message(upstream_status: dict[str, Any]) -> str | None:
    message = upstream_status.get("upstream_pairing_message")
    return message if isinstance(message, str) and message else None


def _upstream_fault(upstream_status: dict[str, Any]) -> Fault | None:
    state = upstream_status.get("upstream_pairing_state")
    if not isinstance(state, str):
        return None
    message = _pairing_message(upstream_status)
    if message is not None and DRIVER_INACTIVE_MARKER in message:
        return DRIVER_INACTIVE.issue(message)
    spec = PAIRING_FAULTS.get(state)
    return None if spec is None else spec.issue(state)
