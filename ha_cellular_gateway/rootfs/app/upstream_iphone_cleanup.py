from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from .command import RunCommand
from .errors import GatewayError
from .upstream_iphone_resolver import external_lease
from .upstream_lease import (
    lease_lock,
    load_app_lease_record,
    write_app_lease_record,
)

if TYPE_CHECKING:
    from .upstream_iphone_runtime import IPhoneUsbRuntime


def discard_owned_lease(
    runtime: IPhoneUsbRuntime,
    run: RunCommand,
) -> None:
    runtime.stop_dhcp()
    try:
        with lease_lock(runtime.lease_lock_path, exclusive=True):
            record = load_app_lease_record(runtime.lease_path)
            if runtime.lease_path.exists() and record is None:
                raise GatewayError("iPhone USB lease record is invalid")
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
        record = load_app_lease_record(runtime.lease_path)
        if record:
            write_app_lease_record(
                runtime.lease_path,
                record[0],
                record[1],
                record[2],
            )
        raise
