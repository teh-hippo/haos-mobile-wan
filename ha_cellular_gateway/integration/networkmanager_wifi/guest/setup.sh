#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
install -d -m 0755 /var/log/haos-wan-lab

cat >/usr/sbin/policy-rc.d <<'EOF'
#!/bin/sh
exit 101
EOF
chmod 0755 /usr/sbin/policy-rc.d
trap 'rm -f /usr/sbin/policy-rc.d' EXIT

apt-get update -qq
apt-get install -y --no-install-recommends \
  apparmor \
  curl \
  hostapd \
  iproute2 \
  iptables \
  iw \
  kmod \
  linux-image-amd64 \
  network-manager \
  procps \
  python3 \
  python3-dbus \
  rfkill \
  wireless-regdb \
  wpasupplicant

rm -f /usr/sbin/policy-rc.d
trap - EXIT

management_interface="$(ip -4 route show default | awk 'NR == 1 {print $5}')"
[ -n "$management_interface" ] || {
  echo "Cannot identify the guest management interface." >&2
  exit 1
}
cat >/etc/NetworkManager/conf.d/90-haos-wan-lab.conf <<EOF
[keyfile]
unmanaged-devices=interface-name:${management_interface}
EOF

systemctl disable NetworkManager hostapd >/dev/null 2>&1 || true
systemctl stop NetworkManager hostapd >/dev/null 2>&1 || true

if ! modinfo mac80211_hwsim >/dev/null 2>&1; then
  echo "mac80211_hwsim requires a reboot into linux-image-amd64." >&2
  exit 75
fi
