from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable
from typing import Any

import dbus

from app.command import CommandRunner
from app.nm_inventory import NmInventory
from app.nm_metadata import DbusWifiProfileMetadata
from app.nm_profile import NmProfile, ProfileSpec
from app.nm_profile_specs import USB_PROFILE_UUID, usb_profile_spec
from app.networkmanager_invariants import (
    main_default_present,
    networkmanager_routes,
    rule_selects_table,
)
from app.wifi_custody import MARKER_KEY, WifiCustodian
from nmcli_harness import NmcliHarnessRunner


DEVICE = "nmwan0"
PHONE = "phone0"
ROUTE_TABLE = 202
FOREIGN_UUID = "4a229445-9e75-45a6-9a0a-8d9ea2a75a01"
CUSTODY_UUID = "4a229445-9e75-45a6-9a0a-8d9ea2a75a02"
WIFI_UUID = "4a229445-9e75-45a6-9a0a-8d9ea2a75a03"
LEAK_UUID = "4a229445-9e75-45a6-9a0a-8d9ea2a75a04"
INERT_UUID = "4a229445-9e75-45a6-9a0a-8d9ea2a75a05"
FIXED_UUIDS = (
    USB_PROFILE_UUID,
    FOREIGN_UUID,
    CUSTODY_UUID,
    WIFI_UUID,
    LEAK_UUID,
    INERT_UUID,
)
LEASE_ADDRESS = "192.0.2.100/24"
LEASE_GATEWAY = "192.0.2.1"
HARNESS_DIR = "/run/networkmanager-integration"
# DHCP peer processes started for realised veth links, tracked so main() can
# guarantee teardown on every exit path.
_ACTIVE_DNSMASQ: list["subprocess.Popen[bytes]"] = []

# Synthetic lab-only secret. It is never printed and is not a real user's PSK.
SYNTHETIC_PSK = "lab-synthetic-psk-01"
LAB_MARKER_VALUE = "02:00:00:00:00:aa|1|"


class TracingRun:
    def __init__(self) -> None:
        self.runner = NmcliHarnessRunner(CommandRunner())
        self.events: list[tuple[str, tuple[str, ...]]] = []

    def __call__(
        self,
        *args: str,
        check: bool = True,
        timeout: int = 20,
    ) -> subprocess.CompletedProcess[str]:
        self.events.append(("command", args))
        return self.runner.run(list(args), check=check, timeout=timeout)


class TracingMetadata:
    """Production D-Bus metadata store that records mutation order in the trace."""

    def __init__(self, uuid: str, events: list[tuple[str, tuple[str, ...]]]) -> None:
        self.store = DbusWifiProfileMetadata(uuid)
        self.events = events

    def read(self, key: str) -> str | None:
        return self.store.read(key)

    def write(self, key: str, value: str) -> None:
        self.events.append(("metadata-write", (key,)))
        self.store.write(key, value)

    def clear(self, key: str) -> None:
        self.events.append(("metadata-clear", (key,)))
        self.store.clear(key)


def require(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def event_index(
    events: list[tuple[str, tuple[str, ...]]],
    predicate: Callable[[tuple[str, tuple[str, ...]]], bool],
) -> int:
    for index, event in enumerate(events):
        if predicate(event):
            return index
    raise AssertionError("Expected event was not recorded")


def wait_for(predicate: Callable[[], bool], message: str, seconds: float = 15) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.25)
    raise AssertionError(message)


def test_nmcli_radio_output_shape() -> None:
    runner = CommandRunner()
    combined = runner.run(
        ["nmcli", "-g", "WIFI-HW,WIFI", "radio"],
        check=False,
    )
    require(combined.returncode == 0, "real nmcli radio query failed")
    rows = (combined.stdout or "").splitlines()
    require(
        len(rows) == 1 and ":" in rows[0],
        "real nmcli did not return one tabular multi-field row",
    )
    for field in ("WIFI-HW", "WIFI"):
        result = runner.run(["nmcli", "-g", field, "radio"], check=False)
        require(result.returncode == 0, f"real nmcli {field} query failed")
        require(
            len((result.stdout or "").splitlines()) == 1,
            f"real nmcli {field} query was not scalar",
        )


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


def read_psk(run: TracingRun, uuid: str) -> str:
    """Read the stored WPA PSK the same way production does, and never log it."""
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


def realise_link(run: TracingRun) -> "subprocess.Popen[bytes]":
    """Create the carrier-up veth and DHCP peer, then wait for NM to see it.

    NetworkManager is already running, so realising the link here exercises the
    real one-time have_connection_for_device gate exactly as HAOS does.
    """
    run("ip", "link", "add", DEVICE, "type", "veth", "peer", "name", PHONE)
    run("ip", "address", "add", "192.0.2.1/24", "dev", PHONE)
    run("ip", "link", "set", PHONE, "up")
    run("ip", "link", "set", DEVICE, "up")
    # Each realisation gets a fresh single-address pool. Every veth is created
    # with a new MAC, so a lease database carried over from a prior scenario
    # would leave the only address bound to a stale client and starve DHCP.
    lease_file = os.path.join(HARNESS_DIR, "dnsmasq.leases")
    if os.path.exists(lease_file):
        os.remove(lease_file)
    log = open(os.path.join(HARNESS_DIR, "dnsmasq.log"), "ab")
    proc = subprocess.Popen(
        [
            "dnsmasq",
            "--keep-in-foreground",
            "--port=0",
            f"--interface={PHONE}",
            "--bind-interfaces",
            "--except-interface=lo",
            f"--dhcp-leasefile={lease_file}",
            "--dhcp-authoritative",
            "--dhcp-range=192.0.2.100,192.0.2.100,255.255.255.0,1h",
            "--dhcp-option=option:router,192.0.2.1",
            "--dhcp-option=option:dns-server,192.0.2.1",
            "--log-dhcp",
        ],
        stdout=log,
        stderr=log,
    )
    wait_for(
        lambda: device_present(run),
        "NetworkManager did not realise the veth device",
    )
    _ACTIVE_DNSMASQ.append(proc)
    return proc


def destroy_link(
    run: TracingRun, proc: "subprocess.Popen[bytes] | None"
) -> None:
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    if proc is not None and proc in _ACTIVE_DNSMASQ:
        _ACTIVE_DNSMASQ.remove(proc)
    run("ip", "link", "delete", DEVICE, "type", "veth", check=False)
    wait_for(
        lambda: not device_present(run),
        "veth device was not removed",
    )


def drop_generated_connections(run: TracingRun) -> None:
    """Remove any NetworkManager-generated connection so cleanup stays exact."""
    run("nmcli", "-w", "5", "device", "disconnect", DEVICE, check=False)
    listing = (
        run(
            "nmcli",
            "--escape",
            "no",
            "-g",
            "UUID",
            "connection",
            "show",
            check=False,
        ).stdout
        or ""
    )
    for uuid in listing.split():
        if uuid not in FIXED_UUIDS:
            run("nmcli", "connection", "delete", "uuid", uuid, check=False)


def test_inert_creation_controls(run: TracingRun) -> None:
    """Paired controls run through NetworkManager's real realisation gate.

    Each control installs its profile before the carrier-up veth exists, so the
    one-time have_connection_for_device gate behaves as it does on HAOS.
    """
    # Negative control (mandatory, non-vacuous): an autoconnectable profile with
    # no route isolation is present at realisation, so NM auto-activates it and
    # leaks a default into the main table.
    run(
        "nmcli",
        "connection",
        "add",
        "type",
        "ethernet",
        "con-name",
        "nm-lab-leak",
        "connection.uuid",
        LEAK_UUID,
        "connection.interface-name",
        DEVICE,
        "connection.autoconnect",
        "yes",
        "ipv4.method",
        "auto",
        "ipv6.method",
        "disabled",
    )
    proc = realise_link(run)
    try:
        wait_for(
            lambda: active_uuid(run) == LEAK_UUID,
            "autoconnectable profile did not auto-activate at realisation",
        )
        wait_for(
            lambda: main_default_present(run, DEVICE),
            "NetworkManager did not leak the mobile default into the main table",
        )
        require(
            networkmanager_routes(run, ROUTE_TABLE) == [],
            "the leaked default was unexpectedly isolated in table 202",
        )
    finally:
        destroy_link(run, proc)
        run("nmcli", "connection", "delete", "uuid", LEAK_UUID, check=False)
    require(not profile_exists(run, LEAK_UUID), "leak control profile remains")

    # Positive control: the production inert profile is present at realisation,
    # so NM neither generates a default nor activates it.
    profile = NmProfile(
        run, veth_spec(INERT_UUID, "nm-lab-inert", autoconnect="no")
    )
    profile.create()
    require(profile.inspect().state == "exact", "inert profile is not exact")
    proc = realise_link(run)
    try:
        time.sleep(2)
        require(active_uuid(run) != INERT_UUID, "inert profile auto-activated")
        require(not device_ipv4(run), "inert profile obtained an address")
        require(
            not main_default_present(run, DEVICE),
            "inert profile leaked a default into the main table",
        )
        require(
            networkmanager_routes(run, ROUTE_TABLE) == [],
            "inert profile installed an isolated lease before activation",
        )
        _activate_inert(run, profile)

        # Same-link delete/recreate without global no-auto-default masking: the
        # realisation gate already passed with a matching profile, so churning
        # the profile over the still-realised device wires no default.
        profile.deactivate()
        profile.delete()
        wait_for(
            lambda: active_uuid(run) == "" and not device_ipv4(run),
            "device did not release the lease on delete",
        )
        require(
            not main_default_present(run, DEVICE),
            "the same-link profile gap wired a default into the main table",
        )
        require(
            networkmanager_routes(run, ROUTE_TABLE) == [],
            "the same-link profile gap left an isolated route",
        )
        profile.create()
        time.sleep(2)
        require(
            active_uuid(run) != INERT_UUID, "recreated inert profile activated"
        )
        require(
            not main_default_present(run, DEVICE),
            "recreated inert profile leaked a default into the main table",
        )
        _activate_inert(run, profile)
    finally:
        run("nmcli", "connection", "down", "uuid", INERT_UUID, check=False)
        run("nmcli", "connection", "delete", "uuid", INERT_UUID, check=False)
        destroy_link(run, proc)
    require(not profile_exists(run, INERT_UUID), "inert control profile remains")


def test_generated_default_safety(run: TracingRun) -> None:
    """Honest safety cases for scenarios the production fix does not cover.

    When a device is realised with no matching profile, NetworkManager may
    generate a default wired connection and wire a default into the main table.
    The production inert-create fix has no bearing on this; the app's
    kernel-truth main-table safety must still detect it fail-closed.
    """
    # Profile-absent first realisation.
    proc = realise_link(run)
    try:
        time.sleep(3)
        _assert_generated_default_is_caught(run, "profile-absent realisation")
    finally:
        drop_generated_connections(run)
        destroy_link(run, proc)

    # Link re-realisation during a profile gap.
    proc = realise_link(run)
    try:
        time.sleep(3)
        _assert_generated_default_is_caught(run, "gap link re-realisation")
    finally:
        drop_generated_connections(run)
        destroy_link(run, proc)


def _assert_generated_default_is_caught(run: TracingRun, label: str) -> None:
    generated = bool(active_uuid(run)) and bool(device_ipv4(run))
    if not generated:
        # This NetworkManager build did not auto-generate a default for the veth
        # device; make no claim that the production fix prevents the scenario.
        return
    require(
        main_default_present(run, DEVICE),
        f"{label}: NetworkManager generated a default lease but the app's "
        "kernel-truth main-table safety did not detect it fail-closed",
    )


def _activate_inert(run: TracingRun, profile: NmProfile) -> None:
    run(
        "nmcli",
        "-w",
        "20",
        "connection",
        "up",
        "uuid",
        INERT_UUID,
        "ifname",
        DEVICE,
        check=False,
    )
    wait_for(
        lambda: active_uuid(run) == INERT_UUID,
        "explicit activation did not bring up the inert profile",
    )
    wait_for(
        lambda: LEASE_ADDRESS in device_ipv4(run),
        "explicit activation did not obtain the DHCP lease",
    )
    routes = networkmanager_routes(run, ROUTE_TABLE)
    require(
        any(
            route.get("dst") == "default"
            and route.get("gateway") == LEASE_GATEWAY
            and route.get("dev") == DEVICE
            for route in routes
        ),
        "explicit activation did not isolate the default in table 202",
    )
    require(
        not main_default_present(run, DEVICE),
        "explicit activation leaked a default into the main table",
    )
    require(
        not rule_selects_table(run, ROUTE_TABLE),
        "explicit activation added a policy rule for the isolated table",
    )


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
    # Install the foreign profile before the device is realised so NM's one-time
    # gate is satisfied and no generated default is created; NM then
    # auto-activates it (autoconnect yes) when the carrier-up veth appears.
    foreign = NmProfile(
        run,
        veth_spec(FOREIGN_UUID, "nm-lab-foreign", autoconnect="yes"),
    )
    foreign.create()
    proc = realise_link(run)
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
        check=False,
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
    metadata = TracingMetadata(CUSTODY_UUID, run.events)
    custodian = WifiCustodian(
        DEVICE,
        run,
        custody_profile,
        metadata=metadata,
        excluded_uuids=lambda: {CUSTODY_UUID},
    )
    hold_errors = custodian.hold(None)
    require(
        hold_errors == [],
        f"custodian could not hold nmwan0: {hold_errors!r}",
    )
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

    gate_errors = custodian.apply_gate(persist_marker)
    require(
        gate_errors == [],
        f"custodian did not displace foreign: {gate_errors!r}",
    )
    marker_index = event_index(
        run.events[events_before_gate:],
        lambda event: event[0] == "metadata-write" and event[1] == (MARKER_KEY,),
    ) + events_before_gate
    persist_index = event_index(
        run.events[events_before_gate:],
        lambda event: event[0] == "persist-marker",
    ) + events_before_gate
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
        metadata=DbusWifiProfileMetadata(CUSTODY_UUID),
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
    if proc in _ACTIVE_DNSMASQ:
        _ACTIVE_DNSMASQ.remove(proc)
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
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


def test_wifi_marker_preserves_secret(run: TracingRun) -> None:
    """A Wi-Fi profile's PSK and every other setting survive marker changes."""
    try:
        created = run(
            "nmcli",
            "connection",
            "add",
            "type",
            "wifi",
            "con-name",
            "nm-lab-psk",
            "connection.uuid",
            WIFI_UUID,
            "ifname",
            "*",
            "ssid",
            "LabHotspot",
            "connection.autoconnect",
            "no",
            "wifi-sec.key-mgmt",
            "wpa-psk",
            "wifi-sec.psk",
            SYNTHETIC_PSK,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise AssertionError("synthetic Wi-Fi profile creation failed") from None
    require(
        created.returncode == 0,
        "synthetic Wi-Fi profile creation failed",
    )
    secret_before = read_psk(run, WIFI_UUID)
    # Compare exactly, but never put either value in the failure message.
    require(secret_before == SYNTHETIC_PSK, "synthetic PSK was not stored")
    settings_before = get_settings(WIFI_UUID)
    require(
        "user" not in settings_before,
        "synthetic profile unexpectedly carried user metadata",
    )

    metadata = DbusWifiProfileMetadata(WIFI_UUID)
    metadata.write(MARKER_KEY, LAB_MARKER_VALUE)
    require(
        metadata.read(MARKER_KEY) == LAB_MARKER_VALUE,
        "marker did not persist through the production D-Bus helper",
    )
    require(
        read_psk(run, WIFI_UUID) == secret_before,
        "writing the marker altered the Wi-Fi PSK",
    )
    settings_marked = get_settings(WIFI_UUID)
    require(
        settings_marked.get("user", {}).get("data", {}).get(MARKER_KEY)
        == LAB_MARKER_VALUE,
        "marker is missing from user.data after a D-Bus write",
    )
    require(
        without_user_setting(settings_marked) == without_user_setting(settings_before),
        "writing the marker altered other profile settings",
    )

    metadata.clear(MARKER_KEY)
    require(metadata.read(MARKER_KEY) is None, "marker was not cleared")
    require(
        read_psk(run, WIFI_UUID) == secret_before,
        "clearing the marker altered the Wi-Fi PSK",
    )
    settings_cleared = get_settings(WIFI_UUID)
    require(
        MARKER_KEY not in settings_cleared.get("user", {}).get("data", {}),
        "marker remained in user.data after being cleared",
    )
    require(
        without_user_setting(settings_cleared) == without_user_setting(settings_before),
        "clearing the marker altered other profile settings",
    )

    run("nmcli", "connection", "delete", "uuid", WIFI_UUID, check=False)
    require(
        not profile_exists(run, WIFI_UUID),
        "synthetic Wi-Fi profile remains after cleanup",
    )


def _teardown_active_links(run: TracingRun) -> None:
    for proc in list(_ACTIVE_DNSMASQ):
        destroy_link(run, proc)
    run("ip", "link", "delete", DEVICE, "type", "veth", check=False)
    delete_fixed_profiles(run)


def main() -> None:
    test_nmcli_radio_output_shape()
    run = TracingRun()
    delete_fixed_profiles(run)
    try:
        test_production_profile_and_inventory(run)
        test_inert_creation_controls(run)
        test_generated_default_safety(run)
        test_custody_dhcp_and_cleanup(run)
        test_wifi_marker_preserves_secret(run)
        print("NetworkManager integration lab passed")
    finally:
        _teardown_active_links(run)


if __name__ == "__main__":
    main()
