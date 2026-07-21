#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"
GUEST_DIR="${SCRIPT_DIR}/guest"

IMAGE_URL="${QEMU_IMAGE_URL:-https://cloud.debian.org/images/cloud/trixie/latest/debian-13-generic-amd64.qcow2}"
IMAGE_SHA512="${QEMU_IMAGE_SHA512:-78f658893d7aecb56288b86afebb72dcdb1a636e8e9db8bda64851a308697794678ceb5cd3b7c86afd5fb892afbc6baf9d2dbaceb7855347fde8660e8d68e667}"
CACHE_DIR="${QEMU_CACHE_DIR:-${HOME}/.cache/haos-mobile-wan-qemu}"
RUN_ROOT="${QEMU_RUN_ROOT:-${TMPDIR:-/tmp}/haos-mobile-wan-qemu}"
LOG_ROOT="${QEMU_LOG_ROOT:-${SCRIPT_DIR}/logs}"
LAB_EXPECT="${LAB_EXPECT:-fixed}"

for command in \
  curl genisoimage python3 qemu-img qemu-system-x86_64 rsync setsid sha512sum \
  ssh ssh-keygen; do
  command -v "$command" >/dev/null || {
    echo "Required command is unavailable: $command" >&2
    exit 1
  }
done

[ "$(uname -m)" = "x86_64" ] || {
  echo "The Wi-Fi lab requires an x86_64 host." >&2
  exit 1
}
[ -r /dev/kvm ] && [ -w /dev/kvm ] || {
  echo "Usable KVM acceleration is required at /dev/kvm." >&2
  exit 1
}
case "$LAB_EXPECT" in
  legacy|fixed) ;;
  *)
    echo "LAB_EXPECT must be legacy or fixed." >&2
    exit 1
    ;;
esac

mkdir -p "$CACHE_DIR" "$RUN_ROOT" "$LOG_ROOT"
for stale in "$RUN_ROOT"/*; do
  [ -d "$stale" ] || continue
  if [ -r "$stale/qemu.pid" ]; then
    stale_pid="$(cat "$stale/qemu.pid")"
    if kill -0 "$stale_pid" 2>/dev/null; then
      continue
    fi
  fi
  rm -rf -- "$stale"
done

if [ -n "${QEMU_BASE_IMAGE:-}" ]; then
  BASE_IMAGE="$QEMU_BASE_IMAGE"
  EXPECTED_SHA512="${QEMU_BASE_IMAGE_SHA512:?Set QEMU_BASE_IMAGE_SHA512}"
else
  BASE_IMAGE="${CACHE_DIR}/debian-13-generic-amd64.qcow2"
  EXPECTED_SHA512="$IMAGE_SHA512"
  if [ ! -f "$BASE_IMAGE" ]; then
    temporary="${BASE_IMAGE}.download"
    rm -f "$temporary"
    curl -fL --retry 3 --output "$temporary" "$IMAGE_URL"
    mv "$temporary" "$BASE_IMAGE"
  fi
fi

[ -f "$BASE_IMAGE" ] || {
  echo "QEMU base image does not exist: $BASE_IMAGE" >&2
  exit 1
}
actual_sha512="$(sha512sum "$BASE_IMAGE" | awk '{print $1}')"
[ "$actual_sha512" = "$EXPECTED_SHA512" ] || {
  echo "QEMU base image checksum mismatch; update the pinned image metadata." >&2
  exit 1
}

run_id="$(date -u +%Y%m%dT%H%M%SZ)-$$"
RUN_DIR="${RUN_ROOT}/${run_id}"
LOG_DIR="${LOG_ROOT}/${run_id}-${LAB_EXPECT}"
mkdir -p "$RUN_DIR" "$LOG_DIR"

KEY_PATH="${RUN_DIR}/id_ed25519"
KNOWN_HOSTS="${RUN_DIR}/known_hosts"
OVERLAY="${RUN_DIR}/guest.qcow2"
SEED="${RUN_DIR}/seed.iso"
USER_DATA="${RUN_DIR}/user-data"
META_DATA="${RUN_DIR}/meta-data"
QEMU_PID=
SSH_PORT=

ssh_options=()

collect_guest_logs() {
  [ -n "$SSH_PORT" ] || return 0
  [ -f "$KEY_PATH" ] || return 0
  rsync -a \
    -e "ssh ${ssh_options[*]}" \
    "lab@127.0.0.1:/var/log/haos-wan-lab/" \
    "${LOG_DIR}/guest/" >/dev/null 2>&1 || true
  ssh "${ssh_options[@]}" lab@127.0.0.1 \
    "sudo journalctl -b --no-pager" \
    >"${LOG_DIR}/journal.log" 2>/dev/null || true
}

cleanup() {
  status=$?
  trap - EXIT INT TERM
  collect_guest_logs
  if [ -n "$QEMU_PID" ] && kill -0 "$QEMU_PID" 2>/dev/null; then
    kill -TERM -- "-$QEMU_PID" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 "$QEMU_PID" 2>/dev/null || break
      sleep 0.5
    done
    if kill -0 "$QEMU_PID" 2>/dev/null; then
      kill -KILL -- "-$QEMU_PID" 2>/dev/null || true
    fi
    wait "$QEMU_PID" 2>/dev/null || true
  fi
  rm -rf -- "$RUN_DIR"
  exit "$status"
}
trap cleanup EXIT INT TERM

ssh-keygen -q -t ed25519 -N "" -f "$KEY_PATH"
public_key="$(cat "${KEY_PATH}.pub")"
sed "s|__SSH_PUBLIC_KEY__|${public_key}|" \
  "${GUEST_DIR}/user-data" >"$USER_DATA"
sed "s|__INSTANCE_ID__|${run_id}|" \
  "${GUEST_DIR}/meta-data" >"$META_DATA"
genisoimage -quiet -output "$SEED" -volid cidata -joliet -rock \
  "$USER_DATA" "$META_DATA"

qemu-img create -q -f qcow2 -F qcow2 -b "$BASE_IMAGE" "$OVERLAY"
qemu-img resize -q "$OVERLAY" 16G
SSH_PORT="$(python3 - <<'PY'
import socket

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"

ssh_options=(
  -i "$KEY_PATH"
  -p "$SSH_PORT"
  -o BatchMode=yes
  -o ConnectTimeout=5
  -o ServerAliveInterval=10
  -o StrictHostKeyChecking=no
  -o "UserKnownHostsFile=${KNOWN_HOSTS}"
)

export QEMU_OVERLAY="$OVERLAY"
export QEMU_SEED="$SEED"
export QEMU_SSH_PORT="$SSH_PORT"
export QEMU_SERIAL_LOG="${LOG_DIR}/serial.log"
export QEMU_STDERR_LOG="${LOG_DIR}/qemu.stderr.log"
setsid "${SCRIPT_DIR}/qemu.sh" &
QEMU_PID=$!
printf '%s\n' "$QEMU_PID" >"${RUN_DIR}/qemu.pid"

ready=false
for _ in $(seq 1 120); do
  if ssh "${ssh_options[@]}" lab@127.0.0.1 true 2>/dev/null; then
    ready=true
    break
  fi
  kill -0 "$QEMU_PID" 2>/dev/null || break
  sleep 2
done
[ "$ready" = true ] || {
  echo "The QEMU guest did not become reachable over SSH." >&2
  exit 1
}

ssh "${ssh_options[@]}" lab@127.0.0.1 \
  "sudo cloud-init status --wait" >/dev/null
ssh "${ssh_options[@]}" lab@127.0.0.1 \
  "mkdir -p /home/lab/haos-mobile-wan"
rsync -a --delete \
  --exclude .git \
  --exclude __pycache__ \
  --exclude '*.pyc' \
  --exclude 'integration/networkmanager_wifi/logs' \
  -e "ssh ${ssh_options[*]}" \
  "${REPO_ROOT}/" \
  "lab@127.0.0.1:/home/lab/haos-mobile-wan/"

set +e
ssh "${ssh_options[@]}" lab@127.0.0.1 \
  "sudo /home/lab/haos-mobile-wan/ha_cellular_gateway/integration/networkmanager_wifi/guest/setup.sh"
setup_status=$?
set -e
if [ "$setup_status" -eq 75 ]; then
  ssh "${ssh_options[@]}" lab@127.0.0.1 "sudo reboot" >/dev/null 2>&1 || true
  sleep 5
  ready=false
  for _ in $(seq 1 120); do
    if ssh "${ssh_options[@]}" lab@127.0.0.1 true 2>/dev/null; then
      ready=true
      break
    fi
    sleep 2
  done
  [ "$ready" = true ] || {
    echo "The QEMU guest did not return after its kernel reboot." >&2
    exit 1
  }
  ssh "${ssh_options[@]}" lab@127.0.0.1 \
    "sudo /home/lab/haos-mobile-wan/ha_cellular_gateway/integration/networkmanager_wifi/guest/setup.sh"
elif [ "$setup_status" -ne 0 ]; then
  exit "$setup_status"
fi

# shellcheck disable=SC2029
ssh "${ssh_options[@]}" lab@127.0.0.1 \
  "sudo env LAB_EXPECT=${LAB_EXPECT} /home/lab/haos-mobile-wan/ha_cellular_gateway/integration/networkmanager_wifi/guest/run-tests.sh"

collect_guest_logs
echo "QEMU Wi-Fi integration lab passed (${LAB_EXPECT}); logs: ${LOG_DIR}"
