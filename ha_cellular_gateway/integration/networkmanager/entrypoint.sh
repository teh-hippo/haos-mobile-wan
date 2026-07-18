#!/bin/sh
set -eu

readonly HARNESS_DIR=/run/networkmanager-integration
readonly DBUS_SOCKET=/run/dbus/system_bus_socket
readonly NM_DEVICE=nmwan0
readonly PHONE_DEVICE=phone0
readonly PROFILE_UUIDS="69fc469b-e2b9-52ba-8f8d-20e5a353735b 4a229445-9e75-45a6-9a0a-8d9ea2a75a01 4a229445-9e75-45a6-9a0a-8d9ea2a75a02 4a229445-9e75-45a6-9a0a-8d9ea2a75a03"

DBUS_PID=
DNSMASQ_PID=
NM_PID=

cleanup() {
    status=$?
    trap - EXIT INT TERM

    if [ -S "$DBUS_SOCKET" ]; then
        for uuid in $PROFILE_UUIDS; do
            nmcli connection delete uuid "$uuid" >/dev/null 2>&1 || true
        done
    fi

    for log in dbus networkmanager dnsmasq; do
        if [ -f "$HARNESS_DIR/$log.log" ]; then
            echo "===== $log.log ====="
            cat "$HARNESS_DIR/$log.log"
        fi
    done

    if [ -n "$DNSMASQ_PID" ]; then
        kill -TERM "$DNSMASQ_PID" 2>/dev/null || true
        wait "$DNSMASQ_PID" 2>/dev/null || true
    fi
    if [ -n "$NM_PID" ]; then
        kill -TERM "$NM_PID" 2>/dev/null || true
        wait "$NM_PID" 2>/dev/null || true
    fi
    if [ -n "$DBUS_PID" ]; then
        kill -TERM "$DBUS_PID" 2>/dev/null || true
        wait "$DBUS_PID" 2>/dev/null || true
    fi
    if ip link show "$NM_DEVICE" >/dev/null 2>&1; then
        ip link delete "$NM_DEVICE" type veth
    fi

    exit "$status"
}

wait_for_networkmanager() {
    retries=80
    while [ "$retries" -gt 0 ]; do
        if nmcli -g RUNNING general 2>/dev/null | grep -qx running; then
            return 0
        fi
        retries=$((retries - 1))
        sleep 0.25
    done
    return 1
}

trap cleanup EXIT INT TERM
mkdir -p "$HARNESS_DIR" /run/dbus
rm -f "$DBUS_SOCKET"
export DBUS_SYSTEM_BUS_ADDRESS="unix:path=$DBUS_SOCKET"

ip link add "$NM_DEVICE" type veth peer name "$PHONE_DEVICE"
ip address add 192.0.2.1/24 dev "$PHONE_DEVICE"
ip link set "$PHONE_DEVICE" up
ip link set "$NM_DEVICE" up

DBUS_PID="$(dbus-daemon --system --fork --nopidfile --print-pid=1 2>>"$HARNESS_DIR/dbus.log")"
NetworkManager --no-daemon --config=/etc/NetworkManager/NetworkManager.conf \
    >"$HARNESS_DIR/networkmanager.log" 2>&1 &
NM_PID=$!

if ! wait_for_networkmanager; then
    cat "$HARNESS_DIR/networkmanager.log"
    exit 1
fi

dnsmasq \
    --keep-in-foreground \
    --port=0 \
    --interface="$PHONE_DEVICE" \
    --bind-interfaces \
    --except-interface=lo \
    --dhcp-range=192.0.2.100,192.0.2.100,255.255.255.0,1h \
    --dhcp-option=option:router,192.0.2.1 \
    --dhcp-option=option:dns-server,192.0.2.1 \
    --log-dhcp \
    >"$HARNESS_DIR/dnsmasq.log" 2>&1 &
DNSMASQ_PID=$!

python3 /integration/test_live_nm.py
