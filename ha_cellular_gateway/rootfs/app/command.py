from __future__ import annotations

import json
import subprocess
from collections.abc import Callable


RunCommand = Callable[..., subprocess.CompletedProcess[str]]


def run_json(run: RunCommand, *args: str) -> object:
    return json.loads(run(*args).stdout or "[]")


def stop_process(process: subprocess.Popen[str] | None) -> None:
    if not process or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


class CommandRunner:
    def run(
        self,
        args: list[str],
        *,
        check: bool = True,
        timeout: int = 20,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            check=check,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
