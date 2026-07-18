from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from typing import Any

import dbus

from app.command import CommandRunner
from app.nm_inventory import NmInventory
from app.nm_profile import NmProfile, ProfileSpec
from app.nm_profile_specs import USB_PROFILE_UUID, usb_profile_spec
from app.networkmanager_invariants import (
    main_default_present,
    networkmanager_routes,
    rule_selects_table,
)
from app.wifi_custody import WifiCustodian


DEVICE = "nmwan0"
PHONE = "phone0"
ROUTE_TABLE = 202
FOREIGN_UUID = "4a229445-9e75-45a6-9a0a-8d9ea2a75a01"
CUSTODY_UUID = "4a229445-9e75-45a6-9a0a-8d9ea2a75a02"
FIXED_UUIDS = (USB_PROFILE_UUID, FOREIGN_UUID, CUSTODY_UUID)


class TracingRun:
    def __init__(self) -> None:
        self.runner = CommandRunner()
        self.events: list[tuple[str, tuple[str, ...]]] = []

    def __call__(
        self,
        *args: str,
        check: bool = True,
        timeout: int = 20,
    ) -> subprocess.CompletedProcess[str]:
        self.events.append(("command", args))
        return self.runner.run(list(args), check=check, timeout=timeout)


def require(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def wait_for(predicate: Callable[[], bool], message: str, seconds: float = 15) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.25)
    raise AssertionError(message)


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


# NetworkManager rewrites volatile bookkeeping fields such as
# connection.timestamp on every successful activation. They are not
# user-configurable identity, so normalise them away before comparing.
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


def command_index(
    events: list[tuple[str, tuple[str, ...]]],
    predicate: Callable[[tuple[str, ...]], bool],
) -> int:
    for index, (kind, args) in enumerate(events):
        if kind == "command" and predicate(args):
            return index
    raise AssertionError("Expected command was not issued")


def test_production_profile_and_inventory(run: TracingRun) -> None:
    profile = NmProfile(run, usb_profile_spec())
    profile.create()
    require(profile.inspect().state == "exact", "production USB profile is not exact")
    profiles = {record.uuid: record for record in NmInventory(run).profiles()}
    require(
        profiles[USB_PROFILE_UUID].connection_type == "802-3-ethernet",
        "inventory did not read the production profile",
    )
    profile.delete()
    require(not profile_exists(run, USB_PROFILE_UUID), "production profile remains")


def test_custody_dhcp_and_cleanup(run: TracingRun) -> None:
    unmanaged = run(
        "nmcli",
        "-g",
        "GENERAL.NM-MANAGED",
        "device",
        "show",
        PHONE,
    ).stdout
    require(
        (unmanaged or "").strip().lower() in {"no", "false", "0"},
        "phone0 is not unmanaged",
    )
    run("nmcli", "radio", "wifi", "on")
    run("nmcli", "device", "set", DEVICE, "autoconnect", "yes")

    foreign = NmProfile(
        run,
        veth_spec(FOREIGN_UUID, "nm-lab-foreign", autoconnect="yes"),
    )
    foreign.create()
    run(
        "nmcli",
        "-w",
        "15",
        "connection",
        "up",
        "uuid",
        FOREIGN_UUID,
        "ifname",
        DEVICE,
    )
    wait_for(
        lambda: active_uuid(run) == FOREIGN_UUID,
        "foreign DHCP profile did not activate",
    )
    addresses = run("nmcli", "-g", "IP4.ADDRESS", "device", "show", DEVICE).stdout
    require(
        "192.0.2.100/24" in (addresses or ""),
        "NetworkManager did not obtain the DHCP lease",
    )
    routes = networkmanager_routes(run, ROUTE_TABLE)
    require(
        any(
            route.get("dst") == "default"
            and route.get("gateway") == "192.0.2.1"
            and route.get("dev") == DEVICE
            for route in routes
        ),
        "DHCP default route is not isolated in table 202",
    )
    require(
        not main_default_present(run, DEVICE),
        "NetworkManager added a veth default route to the main table",
    )
    require(
        not rule_selects_table(run, ROUTE_TABLE),
        "NetworkManager added a policy rule for the isolated table",
    )

    before = get_settings(FOREIGN_UUID)
    custody_profile = NmProfile(
        run,
        veth_spec(CUSTODY_UUID, "nm-lab-custody", autoconnect="no"),
    )
    custody_profile.create()
    custodian = WifiCustodian(
        DEVICE,
        run,
        custody_profile,
        excluded_uuids=lambda: {CUSTODY_UUID},
    )
    require(custodian.hold(None) == [], "custodian could not hold nmwan0")
    marker = custodian.marker
    require(marker is not None, "custodian did not capture recovery metadata")
    require(
        marker.prior_active_foreign_uuid == FOREIGN_UUID,
        "custodian did not identify the active foreign profile",
    )
    require(marker.prior_device_autoconnect, "custodian did not capture autoconnect")

    events_before_gate = len(run.events)

    def persist_marker() -> None:
        run.events.append(("persist-marker", ()))
        require(
            custody_profile.matches_identity(),
            "recovery marker was persisted before the app profile was exact",
        )
        require(
            custodian.read_profile_marker() == marker,
            "profile recovery marker was absent before device mutation",
        )

    require(
        custodian.apply_gate(persist_marker) == [],
        "custodian did not displace foreign",
    )
    marker_index = command_index(
        run.events[events_before_gate:],
        lambda args: args[:3] == ("nmcli", "connection", "modify")
        and args[3] == CUSTODY_UUID
        and "user.data" in args,
    ) + events_before_gate
    persist_index = next(
        index
        for index, event in enumerate(run.events)
        if index >= events_before_gate and event[0] == "persist-marker"
    )
    gate_index = command_index(
        run.events[events_before_gate:],
        lambda args: args[:5]
        == ("nmcli", "device", "set", DEVICE, "autoconnect"),
    ) + events_before_gate
    disconnect_index = command_index(
        run.events[events_before_gate:],
        lambda args: args[:4] == ("nmcli", "-w", "5", "device")
        and args[4:] == ("disconnect", DEVICE),
    ) + events_before_gate
    require(
        marker_index < persist_index < gate_index < disconnect_index,
        "recovery marker was not written and persisted before displacement",
    )
    require(not autoconnect(run), "custodian did not close device autoconnect")
    require(active_uuid(run) == "", "foreign connection remains active")
    require(
        get_settings(FOREIGN_UUID) == before,
        "foreign D-Bus GetSettings identity changed during displacement",
    )

    recovered = WifiCustodian(
        DEVICE,
        run,
        custody_profile,
        excluded_uuids=lambda: {CUSTODY_UUID},
    )
    require(
        recovered.read_profile_marker() == marker,
        "a fresh custodian could not recover the profile marker",
    )
    require(
        recovered.release(None, marker, lambda: run.events.append(("persist-release", ())))
        == [],
        "custodian release failed",
    )
    wait_for(
        lambda: active_uuid(run) == FOREIGN_UUID,
        "foreign profile was not restored after release",
    )
    require(autoconnect(run), "custodian did not restore device autoconnect")
    require(
        not profile_exists(run, CUSTODY_UUID),
        "custodian profile remains after release",
    )
    require(
        get_settings(FOREIGN_UUID) == before,
        "foreign D-Bus GetSettings identity changed during release",
    )

    run("ip", "link", "delete", DEVICE, "type", "veth")
    require(
        run("nmcli", "device", "show", DEVICE, check=False).returncode != 0,
        "early veth deletion did not remove the NetworkManager device",
    )
    delete_fixed_profiles(run)
    require(
        not any(profile_exists(run, uuid) for uuid in FIXED_UUIDS),
        "a fixed harness profile remains after cleanup",
    )
    require(
        networkmanager_routes(run, ROUTE_TABLE) == [],
        "routes remain in the isolated table after early link deletion",
    )
    require(
        not rule_selects_table(run, ROUTE_TABLE),
        "a policy rule remains after early link deletion",
    )


def main() -> None:
    run = TracingRun()
    delete_fixed_profiles(run)
    test_production_profile_and_inventory(run)
    test_custody_dhcp_and_cleanup(run)
    print("NetworkManager integration lab passed")


if __name__ == "__main__":
    main()
