from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

from .command import RunCommand
from .errors import GatewayError
from .upstream_iphone_resolver import external_lease
from .upstream_lease import load_app_lease_record

if TYPE_CHECKING:
    from .upstream_iphone_runtime import IPhoneUsbRuntime


def discard_owned_lease(
    runtime: IPhoneUsbRuntime,
    run: RunCommand,
) -> None:
    record = load_app_lease_record(runtime.lease_path)
    if runtime.lease_path.exists() and record is None:
        raise GatewayError("iPhone USB lease record is invalid")
    interface = record[0] if record else None
    try:
        runtime.stop_dhcp()
        if record and (
            runtime.sys_net_root / record[0]
        ).exists():
            run(
                "ip",
                "-4",
                "address",
                "del",
                record[1],
                "dev",
                record[0],
                check=False,
            )
            state = external_lease(run, record[0])
            if record[1] in state.addresses:
                raise GatewayError(
                    "iPhone USB cleanup left its address active"
                )
        runtime.lease_path.unlink(missing_ok=True)
    except (GatewayError, OSError, subprocess.SubprocessError):
        if record:
            runtime.lease_path.parent.mkdir(parents=True, exist_ok=True)
            runtime.lease_path.write_text(
                json.dumps(
                    {
                        "owner": "app",
                        "interface": record[0],
                        "address": record[1],
                        "gateway": record[2],
                    },
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
        raise
