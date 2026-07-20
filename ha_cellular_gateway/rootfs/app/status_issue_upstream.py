from __future__ import annotations

UPSTREAM_TRANSIENT_STATES = {
    "waiting_for_device": (
        "upstream_waiting_for_device",
        "Waiting for a USB upstream device",
    ),
    "waiting_for_hotspot": (
        "upstream_waiting_for_hotspot",
        "Waiting for iPhone Personal Hotspot",
    ),
    "waiting_for_carrier": (
        "upstream_waiting_for_carrier",
        "Waiting for USB tethering carrier",
    ),
    "waiting_for_profile": (
        "upstream_waiting_for_profile",
        "Waiting for the NetworkManager USB profile",
    ),
    "waiting_for_interface": (
        "upstream_waiting_for_interface",
        "Waiting for the iPhone USB network interface",
    ),
    "not_ready": ("upstream_not_ready", "Upstream connectivity is not ready"),
    "waiting_for_trust": (
        "upstream_waiting_for_trust",
        "Waiting for iPhone USB trust confirmation",
    ),
    "waiting_for_unlock": (
        "upstream_waiting_for_unlock",
        "Waiting for iPhone to be unlocked",
    ),
}

UPSTREAM_STABLE_STATES: dict[str, tuple[str, str]] = {
    "daemon_failed": (
        "upstream_daemon_failed",
        "The iPhone USB pairing helper failed to start",
    ),
    "profile_failed": (
        "upstream_profile_failed",
        "The NetworkManager iPhone USB profile could not be configured",
    ),
    "profile_conflict": (
        "upstream_profile_conflict",
        "A different NetworkManager profile controls the USB upstream interface",
    ),
    "invalid_lease": (
        "upstream_invalid_lease",
        "The USB NetworkManager lease is invalid",
    ),
    "multiple_devices": (
        "upstream_multiple_devices",
        "Multiple USB upstream devices detected",
    ),
    "pairing_failed": ("upstream_pairing_failed", "iPhone USB pairing failed"),
}

UPSTREAM_ERRORS: dict[str, tuple[str, str | None, str]] = {
    "USB device access is unavailable; enable the app usb permission": (
        "upstream_usb_access_unavailable",
        "upstream_configuration",
        "USB device access is unavailable; enable the app USB permission",
    ),
    "Wi-Fi upstream is the management interface": (
        "wifi_management_overlap",
        "hotspot_configuration",
        "The Wi-Fi upstream is the management interface",
    ),
    "The dedicated Wi-Fi adapter is the management interface": (
        "wifi_custody_management",
        "hotspot_configuration",
        "The dedicated Wi-Fi adapter is the management interface",
    ),
    "The dedicated Wi-Fi adapter is not present": (
        "wifi_device_missing",
        "hotspot_configuration",
        "The dedicated Wi-Fi adapter is not present",
    ),
    "NetworkManager does not manage the dedicated Wi-Fi adapter": (
        "wifi_device_unmanaged",
        "hotspot_configuration",
        "NetworkManager does not manage the dedicated Wi-Fi adapter",
    ),
    "The Wi-Fi radio is turned off": (
        "wifi_radio_off",
        "hotspot_configuration",
        "The Wi-Fi radio is turned off",
    ),
    "The Wi-Fi radio is hardware-blocked": (
        "wifi_radio_blocked",
        "hotspot_configuration",
        "The Wi-Fi radio is hardware-blocked",
    ),
    "NetworkManager Wi-Fi radio inspection is unavailable": (
        "wifi_radio_inspection_unavailable",
        None,
        "NetworkManager Wi-Fi radio inspection is unavailable",
    ),
    "A foreign Wi-Fi connection still controls the dedicated adapter": (
        "wifi_displace_failed",
        "hotspot_configuration",
        "A foreign Wi-Fi connection still controls the dedicated adapter",
    ),
    "A legacy Supervisor Wi-Fi profile could not be removed": (
        "lineage_wifi_delete_failed",
        "hotspot_configuration",
        "A legacy Supervisor Wi-Fi profile could not be removed",
    ),
    "The hotspot rejected the configured Wi-Fi password": (
        "hotspot_auth_failed",
        "hotspot_configuration",
        "The hotspot rejected the configured Wi-Fi password",
    ),
    "The hotspot network is not currently visible": (
        "hotspot_target_absent",
        None,
        "The hotspot network is not currently visible",
    ),
    "Associating with the hotspot network": (
        "hotspot_connecting",
        None,
        "Associating with the hotspot network",
    ),
    "Wi-Fi adapter runtime restoration is incomplete": (
        "wifi_restoration_incomplete",
        "hotspot_configuration",
        "The dedicated Wi-Fi adapter runtime state was not fully restored",
    ),
    "The marked Wi-Fi adapter runtime restoration is pending": (
        "wifi_restoration_pending",
        None,
        "The dedicated Wi-Fi adapter runtime restoration is pending",
    ),
    "iPhone USB has a foreign NetworkManager profile": (
        "upstream_foreign_profile",
        "upstream_configuration",
        "A foreign NetworkManager profile can control iPhone USB",
    ),
    "The app-owned iPhone USB profile has unexpected settings": (
        "upstream_profile_drift",
        "upstream_configuration",
        "The app-owned iPhone USB profile has unexpected settings",
    ),
    "The app-owned generic USB profile has unexpected settings": (
        "upstream_profile_drift",
        "upstream_configuration",
        "The app-owned generic USB profile has unexpected settings",
    ),
    "The app-owned Wi-Fi hotspot profile has unexpected settings": (
        "wifi_profile_drift",
        "hotspot_configuration",
        "The app-owned Wi-Fi hotspot profile has unexpected settings",
    ),
    "Wi-Fi hotspot credentials are not configured": (
        "hotspot_credentials_missing",
        "hotspot_configuration",
        "Wi-Fi hotspot credentials are not configured",
    ),
    "NetworkManager Wi-Fi inspection is unavailable": (
        "wifi_inspection_waiting",
        None,
        "Waiting for NetworkManager Wi-Fi inspection",
    ),
}

TRANSIENT_EXACT = {
    "Hotspot Wi-Fi is enabled but not associated",
    "Upstream interface is unavailable",
    "Upstream interface/address is not active",
    "The hotspot network is not currently visible",
    "Associating with the hotspot network",
    "The marked Wi-Fi adapter runtime restoration is pending",
    "NetworkManager Wi-Fi inspection is unavailable",
}
