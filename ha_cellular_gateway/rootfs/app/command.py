from __future__ import annotations

import json
import subprocess
from collections.abc import Callable


RunCommand = Callable[..., subprocess.CompletedProcess[str]]


def run_json(run: RunCommand, *args: str) -> object:
    return json.loads(run(*args).stdout or "[]")


def run_json_table(run: RunCommand, *args: str) -> object:
    result = run(*args, check=False)
    if result.returncode == 0:
        return json.loads(result.stdout or "[]")
    if "FIB table does not exist" in f"{result.stdout}\n{result.stderr}":
        return []
    raise subprocess.CalledProcessError(
        result.returncode,
        args,
        output=result.stdout,
        stderr=result.stderr,
    )


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
