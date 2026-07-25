from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FaultSpec:
    """One fault the app can report, and everything Home Assistant needs for it.

    A spec owns the reported text and the identity derived from it, so the two
    cannot drift apart. ``summary`` of ``None`` means the reported text is
    already the user-facing message.
    """

    id: str
    translation_key: str | None = None
    summary: str | None = None
    transient: bool = False
    exact: tuple[str, ...] = ()
    template: str | None = None
    prefixes: tuple[str, ...] = ()
    contains: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.template is not None and not self.heads:
            raise ValueError(f"{self.id} template has no literal prefix")

    @property
    def heads(self) -> tuple[str, ...]:
        heads = self.prefixes
        if self.template is not None:
            head = self.template.split("{", 1)[0]
            if head:
                heads = (head, *heads)
        return heads

    def render(self, **values: object) -> str:
        if self.template is None:
            raise ValueError(f"{self.id} has no template to render")
        return self.template.format(**values)

    def matches(self, error: str) -> bool:
        return (
            error in self.exact
            or error.startswith(self.heads)
            or any(part in error for part in self.contains)
        )

    def issue(self, error: str) -> Fault:
        return Fault(spec=self, detail=error)


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
