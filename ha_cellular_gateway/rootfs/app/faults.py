"""The faults this app can report, and the identity Home Assistant needs for them.

A fault is described once. The same spec renders the text the app reports and
recognises that text again when the status is assembled, so the wording and the
issue identity derived from it cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FaultSpec:
    id: str
    template: str = ""
    translation_key: str | None = None
    summary: str | None = None
    transient: bool = False
    prefixes: tuple[str, ...] = ()
    contains: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.parameterised and not self.head:
            raise ValueError(f"{self.id} has no literal text before its first value")

    @property
    def parameterised(self) -> bool:
        return "{" in self.template

    @property
    def head(self) -> str:
        return self.template.split("{", 1)[0]

    @property
    def text(self) -> str:
        if self.parameterised:
            raise ValueError(f"{self.id} needs values; call render()")
        return self.template

    def render(self, **values: object) -> str:
        return self.template.format(**values)

    def matches(self, error: str) -> bool:
        if self.template:
            if self.parameterised:
                if error.startswith(self.head):
                    return True
            elif error == self.template:
                return True
        return error.startswith(self.prefixes) or any(
            part in error for part in self.contains
        )

    def issue(self, detail: str) -> Fault:
        return Fault(spec=self, detail=detail)


@dataclass(frozen=True)
class Fault:
    spec: FaultSpec
    detail: str

    @property
    def message(self) -> str:
        return self.spec.summary or self.detail


GENERIC = FaultSpec(id="gateway_runtime_error")

PLACEHOLDER_ERROR = "Safety checks have not run yet"
DRIVER_INACTIVE_MARKER = "ipheth driver is not active"
DRIVER_INACTIVE = FaultSpec(
    id="upstream_driver_inactive",
    translation_key="upstream_configuration",
    summary="The host iPhone USB network driver is not active",
)
