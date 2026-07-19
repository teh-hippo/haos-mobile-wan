#!/usr/bin/env bash
set -euo pipefail

: "${LAB_EXPECT:?}"

ROOT=/home/lab/haos-mobile-wan
LAB_DIR=/run/haos-wan-lab
LOG_DIR=/var/log/haos-wan-lab
AP_NAMESPACE=ap
SSID=haos-wan-lab
SYNTHETIC_PSK=lab-synthetic-psk-01
HOSTAPD_PID=

interface_for_phy() {
  find "/sys/class/ieee80211/$1/device/net" \
    -mindepth 1 -maxdepth 1 -printf '%f\n' | head -n 1
}

usb_driver_interface() {
  for interface in /sys/class/net/*; do
    [ -e "$interface/device/driver" ] || continue
    driver="$(basename "$(readlink -f "$interface/device/driver")")"
    case "$driver" in
      rndis_host|cdc_ether|cdc_ncm)
        basename "$interface"
        return
        ;;
    esac
  done
}

cleanup() {
  status=$?
  trap - EXIT INT TERM
  if [ -r "${LAB_DIR}/hostapd.pid" ]; then
    HOSTAPD_PID="$(cat "${LAB_DIR}/hostapd.pid")"
  fi
  if [ -n "$HOSTAPD_PID" ] && kill -0 "$HOSTAPD_PID" 2>/dev/null; then
    kill -TERM "$HOSTAPD_PID" 2>/dev/null || true
    wait "$HOSTAPD_PID" 2>/dev/null || true
  fi
  systemctl stop NetworkManager >/dev/null 2>&1 || true
  ip netns delete "$AP_NAMESPACE" >/dev/null 2>&1 || true
  modprobe -r mac80211_hwsim >/dev/null 2>&1 || true
  chmod -R a+rX "$LOG_DIR" >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT INT TERM

install -d -m 0755 "$LAB_DIR" "$LOG_DIR"
rm -f "$LAB_DIR"/* "$LOG_DIR"/hostapd.log
systemctl stop NetworkManager >/dev/null 2>&1 || true
ip netns delete "$AP_NAMESPACE" >/dev/null 2>&1 || true
modprobe -r mac80211_hwsim >/dev/null 2>&1 || true

modprobe mac80211_hwsim radios=2
mapfile -t phys < <(find /sys/class/ieee80211 -mindepth 1 -maxdepth 1 \
  -printf '%f\n' | sort)
[ "${#phys[@]}" -eq 2 ] || {
  echo "Expected exactly two hwsim phys." >&2
  exit 1
}
client_phy="${phys[0]}"
ap_phy="${phys[1]}"
client_interface="$(interface_for_phy "$client_phy")"
ap_interface="$(interface_for_phy "$ap_phy")"
[ -n "$client_interface" ] && [ -n "$ap_interface" ] || {
  echo "Cannot resolve hwsim interfaces." >&2
  exit 1
}

generic_interface="$(usb_driver_interface)"
[ -n "$generic_interface" ] || {
  echo "QEMU did not expose a supported generic USB network interface." >&2
  exit 1
}
generic_driver="$(basename "$(readlink -f "/sys/class/net/${generic_interface}/device/driver")")"
generic_bind_id="$(basename "$(readlink -f "/sys/class/net/${generic_interface}/device")")"
printf '%s' "$generic_bind_id" \
  >"/sys/bus/usb/drivers/${generic_driver}/unbind"
for _ in $(seq 1 20); do
  [ ! -e "/sys/class/net/${generic_interface}" ] && break
  sleep 0.1
done
[ ! -e "/sys/class/net/${generic_interface}" ]

ip netns add "$AP_NAMESPACE"
iw phy "$ap_phy" set netns name "$AP_NAMESPACE"
ip netns exec "$AP_NAMESPACE" ip link set lo up
ip netns exec "$AP_NAMESPACE" ip link set "$ap_interface" up
ip netns exec "$AP_NAMESPACE" ip address add 172.20.10.1/28 dev "$ap_interface"

systemctl start NetworkManager
for _ in $(seq 1 40); do
  nmcli -g RUNNING general 2>/dev/null | grep -qx running && break
  sleep 0.25
done
nmcli -g RUNNING general | grep -qx running
nmcli radio wifi on
nmcli device set "$client_interface" managed yes
[ "$(nmcli -g GENERAL.NM-MANAGED device show "$client_interface")" = yes ]

sed \
  -e "s/__AP_INTERFACE__/${ap_interface}/" \
  -e "s/__SYNTHETIC_PSK__/${SYNTHETIC_PSK}/" \
  "${ROOT}/ha_cellular_gateway/integration/networkmanager_wifi/guest/hostapd.conf" \
  >"${LAB_DIR}/hostapd.conf"
ip netns exec "$AP_NAMESPACE" hostapd \
  -B \
  -P "${LAB_DIR}/hostapd.pid" \
  -f "${LOG_DIR}/hostapd.log" \
  "${LAB_DIR}/hostapd.conf"
HOSTAPD_PID="$(cat "${LAB_DIR}/hostapd.pid")"

visible=false
for _ in $(seq 1 40); do
  nmcli device wifi rescan ifname "$client_interface" >/dev/null 2>&1 || true
  if nmcli -g SSID device wifi list ifname "$client_interface" --rescan no \
      | grep -Fxq "$SSID"; then
    visible=true
    break
  fi
  sleep 0.5
done
[ "$visible" = true ] || {
  echo "The hwsim client cannot see the synthetic access point." >&2
  printf '%s\n' "=== client iw ===" >&2
  iw dev >&2 || true
  printf '%s\n' "=== AP iw ===" >&2
  ip netns exec "$AP_NAMESPACE" iw dev >&2 || true
  printf '%s\n' "=== NetworkManager devices ===" >&2
  nmcli device status >&2 || true
  printf '%s\n' "=== radio ===" >&2
  nmcli -f WIFI-HW,WIFI radio >&2 || true
  printf '%s\n' "=== hostapd ===" >&2
  tail -n 80 "${LOG_DIR}/hostapd.log" >&2 || true
  exit 1
}

export PYTHONPATH="${ROOT}/ha_cellular_gateway/rootfs"
export LAB_CLIENT_INTERFACE="$client_interface"
LAB_MANAGEMENT_INTERFACE="$(ip -4 route show default | awk 'NR == 1 {print $5}')"
export LAB_MANAGEMENT_INTERFACE
LAB_MANAGEMENT_ADDRESS="$(ip -4 -o address show dev "$LAB_MANAGEMENT_INTERFACE" \
  | awk 'NR == 1 {print $4}')"
export LAB_MANAGEMENT_ADDRESS
export LAB_SSID="$SSID"
export LAB_PSK="$SYNTHETIC_PSK"
export LAB_AP_NAMESPACE="$AP_NAMESPACE"
export LAB_HOSTAPD_CONFIG="${LAB_DIR}/hostapd.conf"
export LAB_HOSTAPD_LOG="${LOG_DIR}/hostapd.log"
export LAB_HOSTAPD_PID_FILE="${LAB_DIR}/hostapd.pid"
export LAB_GENERIC_USB_DRIVER="$generic_driver"
export LAB_GENERIC_USB_BIND_ID="$generic_bind_id"
python3 \
  "${ROOT}/ha_cellular_gateway/integration/networkmanager_wifi/guest/test_live_wifi.py"

for uuid in \
  463ad2a4-3a0b-56a2-9b86-ec5470d95eb0 \
  9fa59daf-83d4-512a-8324-5caadc830fb8 \
  4a229445-9e75-45a6-9a0a-8d9ea2a75a10; do
  nmcli connection delete uuid "$uuid" >/dev/null 2>&1 || true
done
ip -4 route show table 203 2>/dev/null | grep -q . && {
  echo "Table 203 still contains routes after cleanup." >&2
  exit 1
}
ip -4 rule show | grep -Eq 'lookup (203|cellgw_wifi)' && {
  echo "A Wi-Fi policy rule remains after cleanup." >&2
  exit 1
}

HOSTAPD_PID="$(cat "${LAB_DIR}/hostapd.pid")"
kill -TERM "$HOSTAPD_PID"
wait "$HOSTAPD_PID" 2>/dev/null || true
HOSTAPD_PID=
systemctl stop NetworkManager wpa_supplicant >/dev/null 2>&1 || true
ip netns delete "$AP_NAMESPACE"
modprobe -r mac80211_hwsim

ip netns list | grep -Fxq "$AP_NAMESPACE" && {
  echo "The AP namespace remains after cleanup." >&2
  exit 1
}
pgrep -x hostapd >/dev/null && {
  echo "A hostapd process remains after cleanup." >&2
  exit 1
}
pgrep -x wpa_supplicant >/dev/null && {
  echo "A wpa_supplicant process remains after cleanup." >&2
  exit 1
}

echo "Guest hwsim test passed (${LAB_EXPECT})."
