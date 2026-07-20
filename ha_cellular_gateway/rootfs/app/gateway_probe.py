from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .gateway import GatewayEngine
    from .upstream_models import ResolvedUpstream


def probe_upstream(
    engine: GatewayEngine,
    upstream: ResolvedUpstream | None,
) -> tuple[bool, str | None]:
    if upstream is None:
        return False, None
    try:
        result = engine._run(
            "curl",
            "-4",
            "-fsS",
            "--interface",
            upstream.ip,
            "--max-time",
            "10",
            "https://www.cloudflare.com/cdn-cgi/trace",
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False, None
    if result.returncode != 0:
        return False, None
    for line in result.stdout.splitlines():
        if line.startswith("ip="):
            return True, line.partition("=")[2]
    return True, None
