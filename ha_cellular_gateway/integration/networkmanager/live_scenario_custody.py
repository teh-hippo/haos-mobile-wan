from __future__ import annotations

import subprocess

from app.networkmanager_invariants import (
    main_default_present,
    networkmanager_routes,
    rule_selects_table,
)
from app.nm_metadata import DbusWifiProfileMetadata
from app.nm_profile import NmProfile
from app.wifi_custody import MARKER_KEY, WifiCustodian
from live_constants import (
    CUSTODY_UUID,
    DEVICE,
    FIXED_UUIDS,
    FOREIGN_UUID,
    PHONE,
    ROUTE_TABLE,
)
from live_dbus import (
    active_uuid,
    autoconnect,
    delete_fixed_profiles,
    get_settings,
    profile_exists,
    veth_spec,
)
from live_link import realise_link, untrack_process
from live_tracing import (
    TracingMetadata,
    TracingRun,
    command_index,
    event_index,
    require,
    wait_for,
)


def test_custody_dhcp_and_cleanup(run: TracingRun) -> None:
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
    marker_index = (
        event_index(
            run.events[events_before_gate:],
            lambda event: event[0] == "metadata-write" and event[1] == (MARKER_KEY,),
        )
        + events_before_gate
    )
    persist_index = (
        event_index(
            run.events[events_before_gate:],
            lambda event: event[0] == "persist-marker",
        )
        + events_before_gate
    )
    gate_index = (
        command_index(
            run.events[events_before_gate:],
            lambda args: args[:5] == ("nmcli", "device", "set", DEVICE, "autoconnect"),
        )
        + events_before_gate
    )
    disconnect_index = (
        command_index(
            run.events[events_before_gate:],
            lambda args: (
                args[:4] == ("nmcli", "-w", "5", "device")
                and args[4:] == ("disconnect", DEVICE)
            ),
        )
        + events_before_gate
    )
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
        recovered.release(
            None, marker, lambda: run.events.append(("persist-release", ()))
        )
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
    untrack_process(proc)
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
