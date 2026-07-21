from __future__ import annotations

import time

from app.networkmanager_invariants import (
    main_default_present,
    networkmanager_routes,
    rule_selects_table,
)
from app.nm_profile import NmProfile
from live_constants import (
    DEVICE,
    INERT_UUID,
    LEAK_UUID,
    LEASE_ADDRESS,
    LEASE_GATEWAY,
    ROUTE_TABLE,
)
from live_dbus import active_uuid, device_ipv4, profile_exists, veth_spec
from live_link import destroy_link, drop_generated_connections, realise_link
from live_tracing import TracingRun, require, wait_for


def test_inert_creation_controls(run: TracingRun) -> None:
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

    profile = NmProfile(run, veth_spec(INERT_UUID, "nm-lab-inert", autoconnect="no"))
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
        require(active_uuid(run) != INERT_UUID, "recreated inert profile activated")
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
    proc = realise_link(run)
    try:
        time.sleep(3)
        _assert_generated_default_is_caught(run, "profile-absent realisation")
    finally:
        drop_generated_connections(run)
        destroy_link(run, proc)

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
