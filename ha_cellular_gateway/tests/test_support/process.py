from __future__ import annotations

import subprocess


class Result:
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
    def __init__(
        self,
        *,
        running: bool = True,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
        ignore_terminate: bool = False,
    ) -> None:
        self.running = running
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.ignore_terminate = ignore_terminate
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self) -> int | None:
        return None if self.running else self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1
        if not self.ignore_terminate:
            self.running = False

    def kill(self) -> None:
        self.kill_calls += 1
        self.running = False

    def wait(self, timeout: int = 5) -> int:
        if self.running:
            raise subprocess.TimeoutExpired("fake-process", timeout)
        return self.returncode

    def communicate(self, timeout: int = 1) -> tuple[str, str]:
        self.running = False
        return self.stdout, self.stderr
