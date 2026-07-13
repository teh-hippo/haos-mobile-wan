from __future__ import annotations

import subprocess


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
