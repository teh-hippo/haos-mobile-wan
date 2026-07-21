from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from .command import RunCommand
from .errors import GatewayError

ACTIVATION_COOLDOWN_SECONDS = 30

INERT_CREATE_SETTINGS: tuple[tuple[str, str], ...] = (
    ("connection.autoconnect", "no"),
    ("connection.autoconnect-retries", "0"),
)


def inert_create_args(create_args: tuple[str, ...]) -> tuple[str, ...]:
    inert_keys = {key for key, _ in INERT_CREATE_SETTINGS}
    kept: list[str] = []
    for key, value in zip(create_args[::2], create_args[1::2]):
        if key not in inert_keys:
            kept += [key, value]
    for key, value in INERT_CREATE_SETTINGS:
        kept += [key, value]
    return tuple(kept)


@dataclass(frozen=True)
class ProfileSpec:
    key: str
    uuid: str
    name: str
    connection_type: str
    create_args: tuple[str, ...]
    settings: tuple[tuple[str, str], ...]

    @property
    def expected(self) -> dict[str, str]:
        return {
            "connection.uuid": self.uuid,
            "connection.id": self.name,
            "connection.type": self.connection_type,
            **dict(self.settings),
        }

    @property
    def read_fields(self) -> tuple[str, ...]:
        return tuple(self.expected)

    @property
    def fingerprint(self) -> dict[str, str]:
        return {
            field: value
            for field, value in self.expected.items()
            if field != "802-11-wireless-security.psk"
        }


@dataclass(frozen=True)
class ProfileInspection:
    state: str
    drifted_fields: tuple[str, ...] = ()


class NmProfile:
    def __init__(
        self,
        run: RunCommand,
        spec: ProfileSpec,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.run = run
        self.spec = spec
        self.monotonic = monotonic
        self._last_activation: dict[str, float] = {}

    def inspect(self) -> ProfileInspection:
        settings = self.settings()
        if settings is None:
            return ProfileInspection("missing")
        drifted = tuple(
            field
            for field, expected in self.spec.expected.items()
            if normalise_setting(settings.get(field, "")) != expected
        )
        return ProfileInspection("exact" if not drifted else "drifted", drifted)

    def matches_fingerprint(self, fingerprint: dict[str, str]) -> bool:
        settings = self.settings()
        if settings is None:
            return False
        return all(
            normalise_setting(settings.get(field, "")) == expected
            for field, expected in fingerprint.items()
        )

    def matches_identity(self) -> bool:
        return self.matches_fingerprint(
            {
                "connection.uuid": self.spec.uuid,
                "connection.id": self.spec.name,
                "connection.type": self.spec.connection_type,
            }
        )

    def settings(self) -> dict[str, str] | None:
        result = self.run(
            "nmcli",
            "--show-secrets",
            "-g",
            ",".join(self.spec.read_fields),
            "connection",
            "show",
            self.spec.uuid,
            check=False,
        )
        if result.returncode == 10 or (
            result.returncode != 0
            and "no such connection" in (result.stderr or "").lower()
        ):
            return None
        if result.returncode != 0:
            raise GatewayError("Cannot inspect NetworkManager profile")
        values = (result.stdout or "").splitlines()
        return {
            field: values[index].strip() if index < len(values) else ""
            for index, field in enumerate(self.spec.read_fields)
        }

    def create(self) -> None:
        add_args = inert_create_args(self.spec.create_args)
        self.run("nmcli", "connection", "add", *add_args)
        self.apply_settings()
        if self.inspect().state != "exact":
            raise GatewayError("NetworkManager profile creation did not converge")

    def apply_settings(self) -> None:
        arguments: list[str] = ["connection", "modify", self.spec.uuid]
        for field, value in self.spec.settings:
            arguments += [field, value]
        self.run("nmcli", *arguments)

    def activate(self, interface: str) -> str:
        active = self.active_uuid(interface)
        if active == self.spec.uuid:
            self._last_activation.pop(interface, None)
            return "active"
        if active:
            return "foreign"
        if self._activation_due(interface):
            self.run(
                "nmcli",
                "--wait",
                "8",
                "connection",
                "up",
                "uuid",
                self.spec.uuid,
                check=False,
                timeout=15,
            )
            self._last_activation[interface] = self.monotonic()
            active = self.active_uuid(interface)
            if active == self.spec.uuid:
                self._last_activation.pop(interface, None)
                return "active"
            if active:
                return "foreign"
        return "waiting"

    def deactivate(self) -> None:
        self.run(
            "nmcli",
            "connection",
            "down",
            "uuid",
            self.spec.uuid,
            check=False,
        )

    def delete(self) -> None:
        self.run(
            "nmcli",
            "connection",
            "delete",
            "uuid",
            self.spec.uuid,
            check=False,
        )
        if self.settings() is not None:
            raise GatewayError("NetworkManager profile deletion did not converge")

    def active_uuid(self, interface: str) -> str:
        result = self.run(
            "nmcli",
            "-g",
            "GENERAL.CON-UUID",
            "device",
            "show",
            interface,
            check=False,
        )
        if result.returncode != 0:
            raise GatewayError("Cannot inspect NetworkManager device")
        value = (result.stdout or "").strip()
        return "" if value == "--" else value

    def device_values(self, interface: str, field: str) -> list[str]:
        result = self.run(
            "nmcli",
            "-g",
            field,
            "device",
            "show",
            interface,
            check=False,
        )
        if result.returncode != 0:
            raise GatewayError("Cannot inspect NetworkManager device addresses")
        return [
            stripped
            for line in (result.stdout or "").splitlines()
            if (stripped := line.strip()) and stripped != "--"
        ]

    def _activation_due(self, interface: str) -> bool:
        previous = self._last_activation.get(interface)
        return (
            previous is None
            or self.monotonic() - previous >= ACTIVATION_COOLDOWN_SECONDS
        )


def normalise_setting(value: str) -> str:
    stripped = value.strip()
    if stripped in {"--", "*"}:
        return ""
    match = re.match(r"^\d+\s*\((.+)\)$", stripped)
    if match:
        return match.group(1)
    return stripped
