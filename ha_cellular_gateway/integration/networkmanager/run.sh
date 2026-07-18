#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/compose.yaml"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/compose.log"

if ! command -v docker >/dev/null 2>&1; then
    echo "Rootful Docker with the Compose plugin is required; Podman is not equivalent." >&2
    exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    echo "Docker Compose plugin is required." >&2
    exit 1
fi
security_options="$(docker info --format '{{json .SecurityOptions}}')" || {
    echo "Docker Engine is unavailable." >&2
    exit 1
}
if printf '%s\n' "$security_options" | grep -qi rootless; then
    echo "Rootful Docker is required; rootless Docker and Podman are not supported." >&2
    exit 1
fi

mkdir -p "$LOG_DIR"
: >"$LOG_FILE"
STATUS_FILE="$LOG_DIR/.compose-status"
rm -f "$STATUS_FILE"

cleanup() {
    status=$?
    trap - EXIT INT TERM
    docker compose -f "$COMPOSE_FILE" stop --timeout 10 || true
    docker compose -f "$COMPOSE_FILE" logs --no-color >>"$LOG_FILE" 2>&1 || true
    docker compose -f "$COMPOSE_FILE" down --volumes --remove-orphans || true
    exit "$status"
}

trap cleanup EXIT INT TERM

# Capture the full build and run output while preserving the real exit status
# of "docker compose up". errexit is relaxed only around the pipeline so the
# status file is always written even when the lab fails.
set +e
{
    docker compose -f "$COMPOSE_FILE" up --build --abort-on-container-exit \
        --exit-code-from networkmanager
    echo "$?" >"$STATUS_FILE"
} 2>&1 | tee "$LOG_FILE"
set -e

run_status="$(cat "$STATUS_FILE" 2>/dev/null || echo 1)"
rm -f "$STATUS_FILE"
exit "$run_status"
