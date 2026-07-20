"""Fake subprocess results and long-running process doubles."""

from __future__ import annotations

import subprocess


class Result:
    """Stand-in for a completed subprocess invocation."""

    def __init__(
        self,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeProcess:
    """Stand-in for a long-running ``subprocess.Popen`` handle."""

    def __init__(
        self,
        *,
        running: bool = True,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.running = running
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def poll(self) -> int | None:
        return None if self.running else self.returncode

    def terminate(self) -> None:
        self.running = False

    def kill(self) -> None:
        self.running = False

    def wait(self, timeout: int = 5) -> int:
        if self.running:
            raise subprocess.TimeoutExpired("fake-process", timeout)
        return self.returncode

    def communicate(self, timeout: int = 1) -> tuple[str, str]:
        self.running = False
        return self.stdout, self.stderr
