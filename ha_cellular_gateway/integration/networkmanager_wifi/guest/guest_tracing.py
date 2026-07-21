from __future__ import annotations

import os
import subprocess
import time

from app.command import CommandRunner
from app.config import GatewayConfig
from app.const import WIFI_HOTSPOT
from app.management import ManagementBaseline
from app.nm_profile_specs import WIFI_PROFILE_UUID

FOREIGN_UUID = "4a229445-9e75-45a6-9a0a-8d9ea2a75a10"
PROFILE_FIELDS = (
    "connection.id",
    "connection.uuid",
    "connection.type",
    "connection.interface-name",
    "connection.autoconnect",
    "802-11-wireless.ssid",
    "ipv4.method",
    "ipv4.addresses",
    "ipv4.gateway",
)


def require(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class TracingRun:
    def __init__(self, interface: str) -> None:
        self.runner = CommandRunner()
        self.interface = interface
        self.commands: list[tuple[str, ...]] = []

    def __call__(
        self,
        *args: str,
        check: bool = True,
        timeout: int = 20,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(args)
        result = self.runner.run(list(args), check=check, timeout=timeout)
        if (
            len(args) >= 6
            and args[:2] == ("nmcli", "-g")
            and args[3:5] == ("device", "show")
            and args[5] == self.interface
            and args[2].split(",")[0] == "GENERAL.PATH"
        ):
            values = (result.stdout or "").splitlines()
            if not values or not values[0].strip(" -*"):
                identity = f"hwsim:{self.interface}"
                values = [identity, *values[1:]] if values else [identity]
                stdout = "\n".join(values) + "\n"
                return subprocess.CompletedProcess(
                    result.args,
                    result.returncode,
                    stdout,
                    result.stderr,
                )
        return result


def config(
    *,
    password: str | None = None,
    connection: str = WIFI_HOTSPOT,
) -> GatewayConfig:
    return GatewayConfig(
        auto_disable_minutes=0,
        mobile_connection=connection,
        upstream_interface=os.environ["LAB_CLIENT_INTERFACE"],
        upstream_address="172.20.10.4/28",
        upstream_gateway="172.20.10.1",
        hotspot_ssid=os.environ["LAB_SSID"],
        hotspot_password=password or os.environ["LAB_PSK"],
        downstream_mac="",
        downstream_address="192.168.80.1/24",
    )


def profile_exists(
    run: TracingRun,
    uuid: str = WIFI_PROFILE_UUID,
) -> bool:
    return (
        run(
            "nmcli",
            "-g",
            "connection.uuid",
            "connection",
            "show",
            uuid,
            check=False,
        ).returncode
        == 0
    )


def wait_for(predicate, message: str, seconds: float = 30) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.5)
    raise AssertionError(message)


def active_uuid(run: TracingRun) -> str:
    result = run(
        "nmcli",
        "-g",
        "GENERAL.CON-UUID",
        "device",
        "show",
        os.environ["LAB_CLIENT_INTERFACE"],
        check=False,
    )
    return (result.stdout or "").strip()


def profile_settings(run: TracingRun, uuid: str) -> tuple[str, ...]:
    result = run(
        "nmcli",
        "-g",
        ",".join(PROFILE_FIELDS),
        "connection",
        "show",
        uuid,
    )
    return tuple((result.stdout or "").splitlines())


def management() -> ManagementBaseline:
    return ManagementBaseline(
        os.environ["LAB_MANAGEMENT_INTERFACE"],
        os.environ["LAB_MANAGEMENT_ADDRESS"],
    )
