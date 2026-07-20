"""Fixed identifiers and paths shared across the NetworkManager lab scenarios."""

from __future__ import annotations

from app.nm_profile_specs import USB_PROFILE_UUID

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

# Synthetic lab-only secret. It is never printed and is not a real user's PSK.
SYNTHETIC_PSK = "lab-synthetic-psk-01"
LAB_MARKER_VALUE = "02:00:00:00:00:aa|1|"
