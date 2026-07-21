from __future__ import annotations

import subprocess
import time
from collections.abc import Callable

from app.command import CommandRunner
from app.nm_metadata import DbusWifiProfileMetadata
from nmcli_harness import NmcliHarnessRunner


class TracingRun:
    def __init__(self) -> None:
        self.runner = NmcliHarnessRunner(CommandRunner())
        self.events: list[tuple[str, tuple[str, ...]]] = []

    def __call__(
        self,
        *args: str,
        check: bool = True,
        timeout: int = 20,
    ) -> subprocess.CompletedProcess[str]:
        self.events.append(("command", args))
        return self.runner.run(list(args), check=check, timeout=timeout)


class TracingMetadata:
    def __init__(self, uuid: str, events: list[tuple[str, tuple[str, ...]]]) -> None:
        self.store = DbusWifiProfileMetadata(uuid)
        self.events = events

    def read(self, key: str) -> str | None:
        return self.store.read(key)

    def write(self, key: str, value: str) -> None:
        self.events.append(("metadata-write", (key,)))
        self.store.write(key, value)

    def clear(self, key: str) -> None:
        self.events.append(("metadata-clear", (key,)))
        self.store.clear(key)


def require(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def event_index(
    events: list[tuple[str, tuple[str, ...]]],
    predicate: Callable[[tuple[str, tuple[str, ...]]], bool],
) -> int:
    for index, event in enumerate(events):
        if predicate(event):
            return index
    raise AssertionError("Expected event was not recorded")


def command_index(
    events: list[tuple[str, tuple[str, ...]]],
    predicate: Callable[[tuple[str, ...]], bool],
) -> int:
    for index, (kind, args) in enumerate(events):
        if kind == "command" and predicate(args):
            return index
    raise AssertionError("Expected command was not issued")


def wait_for(predicate: Callable[[], bool], message: str, seconds: float = 15) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.25)
    raise AssertionError(message)
