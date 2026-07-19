from __future__ import annotations

from dataclasses import dataclass

from .command import RunCommand
from .errors import GatewayError
from .nm_profile import normalise_setting

DEVICE_FIELDS = (
    "GENERAL.PATH",
    "GENERAL.STATE",
    "GENERAL.REASON",
    "GENERAL.CON-UUID",
    "GENERAL.NM-MANAGED",
    "GENERAL.AUTOCONNECT",
)

DISCONNECT_WAIT_SECONDS = 5
ACTIVATION_WAIT_SECONDS = 8


@dataclass(frozen=True)
class DeviceState:
    interface: str
    identity: str
    managed: bool
    autoconnect: bool
    active_uuid: str
    state: str
    reason: str
    radio_software: bool
    radio_hardware: bool


class RadioInspectionError(GatewayError):
    pass


def _show(run: RunCommand, interface: str, fields: tuple[str, ...]) -> list[str] | None:
    result = run(
        "nmcli",
        "-g",
        ",".join(fields),
        "device",
        "show",
        interface,
        check=False,
    )
    if result.returncode != 0:
        return None
    return (result.stdout or "").splitlines()


def _yes(value: str) -> bool:
    return normalise_setting(value).lower() in {"yes", "true", "1"}


def device_identity(run: RunCommand, interface: str) -> str | None:
    values = _show(run, interface, ("GENERAL.PATH",))
    if not values:
        return None
    return normalise_setting(values[0]) or None


def resolve_interface(run: RunCommand, identity: str) -> str | None:
    result = run("nmcli", "-g", "DEVICE", "device", "status", check=False)
    if result.returncode != 0:
        raise GatewayError("Cannot inspect NetworkManager devices")
    for line in (result.stdout or "").splitlines():
        name = line.strip()
        if name and device_identity(run, name) == identity:
            return name
    return None


def _radio_enabled(run: RunCommand, field: str) -> bool:
    result = run("nmcli", "-g", field, "radio", check=False)
    value = normalise_setting(result.stdout or "").lower()
    enabled = {"enabled", "yes", "true", "1"}
    disabled = {"disabled", "no", "false", "0"}
    if result.returncode != 0 or value not in enabled | disabled:
        raise RadioInspectionError("Cannot inspect NetworkManager Wi-Fi radio")
    return value in enabled


def radio_state(run: RunCommand) -> tuple[bool, bool]:
    hardware = _radio_enabled(run, "WIFI-HW")
    software = _radio_enabled(run, "WIFI")
    return software, hardware


def read_device_state(run: RunCommand, interface: str) -> DeviceState:
    values = _show(run, interface, DEVICE_FIELDS)
    if values is None:
        raise GatewayError("Cannot inspect NetworkManager device state")
    fields = {
        field: normalise_setting(values[index]) if index < len(values) else ""
        for index, field in enumerate(DEVICE_FIELDS)
    }
    software, hardware = radio_state(run)
    return DeviceState(
        interface=interface,
        identity=fields["GENERAL.PATH"],
        managed=_yes(fields["GENERAL.NM-MANAGED"]),
        autoconnect=_yes(fields["GENERAL.AUTOCONNECT"]),
        active_uuid=fields["GENERAL.CON-UUID"],
        state=fields["GENERAL.STATE"],
        reason=fields["GENERAL.REASON"],
        radio_software=software,
        radio_hardware=hardware,
    )


def set_device_autoconnect(run: RunCommand, interface: str, value: bool) -> None:
    run(
        "nmcli",
        "device",
        "set",
        interface,
        "autoconnect",
        "yes" if value else "no",
    )


def disconnect_device(run: RunCommand, interface: str) -> None:
    run(
        "nmcli",
        "-w",
        str(DISCONNECT_WAIT_SECONDS),
        "device",
        "disconnect",
        interface,
        check=False,
    )


def cached_ssids(run: RunCommand, interface: str) -> set[str]:
    result = run(
        "nmcli",
        "-g",
        "SSID",
        "device",
        "wifi",
        "list",
        "ifname",
        interface,
        "--rescan",
        "no",
        check=False,
    )
    if result.returncode != 0:
        raise GatewayError("Cannot inspect cached Wi-Fi networks")
    return {
        normalise_setting(line)
        for line in (result.stdout or "").splitlines()
        if normalise_setting(line)
    }


def request_scan(run: RunCommand, interface: str) -> None:
    run("nmcli", "device", "wifi", "rescan", "ifname", interface, check=False)
