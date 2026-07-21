from __future__ import annotations

import os
from typing import Any

import dbus
from app.nm_profile import ProfileSpec
from live_constants import DEVICE, FIXED_UUIDS, ROUTE_TABLE
from live_tracing import TracingRun


def veth_spec(uuid: str, name: str, *, autoconnect: str) -> ProfileSpec:
    return ProfileSpec(
        key=name,
        uuid=uuid,
        name=name,
        connection_type="802-3-ethernet",
        create_args=(
            "type",
            "ethernet",
            "con-name",
            name,
            "connection.uuid",
            uuid,
            "ifname",
            DEVICE,
        ),
        settings=(
            ("connection.interface-name", DEVICE),
            ("connection.autoconnect", autoconnect),
            ("connection.autoconnect-retries", "0"),
            ("ipv4.method", "auto"),
            ("ipv4.route-table", str(ROUTE_TABLE)),
            ("ipv4.ignore-auto-dns", "yes"),
            ("ipv4.never-default", "no"),
            ("ipv4.may-fail", "no"),
            ("ipv6.method", "disabled"),
        ),
    )


def plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    return str(value)


VOLATILE_SETTINGS = {"connection": {"timestamp"}}


def stable_settings(settings: dict[str, Any]) -> dict[str, Any]:
    normalised = plain(settings)
    for group, fields in VOLATILE_SETTINGS.items():
        section = normalised.get(group)
        if isinstance(section, dict):
            for field in fields:
                section.pop(field, None)
    return normalised


def get_settings(uuid: str) -> dict[str, Any]:
    address = os.environ["DBUS_SYSTEM_BUS_ADDRESS"]
    bus = dbus.bus.BusConnection(address)
    manager = bus.get_object(
        "org.freedesktop.NetworkManager",
        "/org/freedesktop/NetworkManager/Settings",
    )
    paths = manager.ListConnections(
        dbus_interface="org.freedesktop.NetworkManager.Settings"
    )
    for path in paths:
        connection = bus.get_object("org.freedesktop.NetworkManager", path)
        settings = connection.GetSettings(
            dbus_interface="org.freedesktop.NetworkManager.Settings.Connection"
        )
        if str(settings["connection"]["uuid"]) == uuid:
            return stable_settings(settings)
    raise AssertionError(f"NetworkManager cannot find connection {uuid} over D-Bus")


def read_psk_without_logging(run: TracingRun, uuid: str) -> str:
    result = run(
        "nmcli",
        "--show-secrets",
        "-g",
        "802-11-wireless-security.psk",
        "connection",
        "show",
        uuid,
    )
    return (result.stdout or "").strip()


def without_user_setting(settings: dict[str, Any]) -> dict[str, Any]:
    return {group: value for group, value in settings.items() if group != "user"}


def profile_exists(run: TracingRun, uuid: str) -> bool:
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


def active_uuid(run: TracingRun) -> str:
    result = run(
        "nmcli",
        "-g",
        "GENERAL.CON-UUID",
        "device",
        "show",
        DEVICE,
    )
    value = (result.stdout or "").strip()
    return "" if value == "--" else value


def autoconnect(run: TracingRun) -> bool:
    value = run(
        "nmcli",
        "-g",
        "GENERAL.AUTOCONNECT",
        "device",
        "show",
        DEVICE,
    ).stdout
    return (value or "").strip().lower() in {"yes", "true", "1"}


def delete_fixed_profiles(run: TracingRun) -> None:
    for uuid in FIXED_UUIDS:
        run("nmcli", "connection", "delete", "uuid", uuid, check=False)


def device_ipv4(run: TracingRun) -> list[str]:
    result = run(
        "nmcli",
        "-g",
        "IP4.ADDRESS",
        "device",
        "show",
        DEVICE,
        check=False,
    )
    return [
        stripped
        for line in (result.stdout or "").splitlines()
        if (stripped := line.strip()) and stripped != "--"
    ]


def device_present(run: TracingRun) -> bool:
    return run("nmcli", "device", "show", DEVICE, check=False).returncode == 0
