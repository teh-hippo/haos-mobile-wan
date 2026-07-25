"""Faults reported by the mobile upstream, plus the iPhone pairing states."""

from __future__ import annotations

from .faults import FaultSpec

UPSTREAM_USB_ACCESS_UNAVAILABLE = FaultSpec(
    id="upstream_usb_access_unavailable",
    translation_key="upstream_configuration",
    summary="USB device access is unavailable; enable the app USB permission",
    template="USB device access is unavailable; enable the app usb permission",
)

WIFI_MANAGEMENT_OVERLAP = FaultSpec(
    id="wifi_management_overlap",
    translation_key="hotspot_configuration",
    summary="The Wi-Fi upstream is the management interface",
    template="Wi-Fi upstream is the management interface",
)

WIFI_CUSTODY_MANAGEMENT = FaultSpec(
    id="wifi_custody_management",
    translation_key="hotspot_configuration",
    summary="The dedicated Wi-Fi adapter is the management interface",
    template="The dedicated Wi-Fi adapter is the management interface",
)

WIFI_DEVICE_MISSING = FaultSpec(
    id="wifi_device_missing",
    translation_key="hotspot_configuration",
    summary="The dedicated Wi-Fi adapter is not present",
    template="The dedicated Wi-Fi adapter is not present",
)

WIFI_DEVICE_UNMANAGED = FaultSpec(
    id="wifi_device_unmanaged",
    translation_key="hotspot_configuration",
    summary="NetworkManager does not manage the dedicated Wi-Fi adapter",
    template="NetworkManager does not manage the dedicated Wi-Fi adapter",
)

WIFI_RADIO_OFF = FaultSpec(
    id="wifi_radio_off",
    translation_key="hotspot_configuration",
    summary="The Wi-Fi radio is turned off",
    template="The Wi-Fi radio is turned off",
)

WIFI_RADIO_BLOCKED = FaultSpec(
    id="wifi_radio_blocked",
    translation_key="hotspot_configuration",
    summary="The Wi-Fi radio is hardware-blocked",
    template="The Wi-Fi radio is hardware-blocked",
)

WIFI_RADIO_INSPECTION_UNAVAILABLE = FaultSpec(
    id="wifi_radio_inspection_unavailable",
    summary="NetworkManager Wi-Fi radio inspection is unavailable",
    template="NetworkManager Wi-Fi radio inspection is unavailable",
)

WIFI_DISPLACE_FAILED = FaultSpec(
    id="wifi_displace_failed",
    translation_key="hotspot_configuration",
    summary="A foreign Wi-Fi connection still controls the dedicated adapter",
    template="A foreign Wi-Fi connection still controls the dedicated adapter",
)

LINEAGE_WIFI_DELETE_FAILED = FaultSpec(
    id="lineage_wifi_delete_failed",
    translation_key="hotspot_configuration",
    summary="A legacy Supervisor Wi-Fi profile could not be removed",
    template="A legacy Supervisor Wi-Fi profile could not be removed",
)

HOTSPOT_AUTH_FAILED = FaultSpec(
    id="hotspot_auth_failed",
    translation_key="hotspot_configuration",
    summary="The hotspot rejected the configured Wi-Fi password",
    template="The hotspot rejected the configured Wi-Fi password",
)

HOTSPOT_TARGET_ABSENT = FaultSpec(
    id="hotspot_target_absent",
    summary="The hotspot network is not currently visible",
    transient=True,
    template="The hotspot network is not currently visible",
)

HOTSPOT_CONNECTING = FaultSpec(
    id="hotspot_connecting",
    summary="Associating with the hotspot network",
    transient=True,
    template="Associating with the hotspot network",
)

WIFI_RESTORATION_INCOMPLETE = FaultSpec(
    id="wifi_restoration_incomplete",
    translation_key="hotspot_configuration",
    summary="The dedicated Wi-Fi adapter runtime state was not fully restored",
    template="Wi-Fi adapter runtime restoration is incomplete",
)

WIFI_RESTORATION_PENDING = FaultSpec(
    id="wifi_restoration_pending",
    summary="The dedicated Wi-Fi adapter runtime restoration is pending",
    transient=True,
    template="The marked Wi-Fi adapter runtime restoration is pending",
)

UPSTREAM_FOREIGN_PROFILE = FaultSpec(
    id="upstream_foreign_profile",
    translation_key="upstream_configuration",
    summary="A foreign NetworkManager profile can control iPhone USB",
    template="iPhone USB has a foreign NetworkManager profile",
)

UPSTREAM_PROFILE_DRIFT = FaultSpec(
    id="upstream_profile_drift",
    translation_key="upstream_configuration",
    summary="The app-owned iPhone USB profile has unexpected settings",
    template="The app-owned iPhone USB profile has unexpected settings",
)

UPSTREAM_PROFILE_DRIFT_2 = FaultSpec(
    id="upstream_profile_drift",
    translation_key="upstream_configuration",
    summary="The app-owned generic USB profile has unexpected settings",
    template="The app-owned generic USB profile has unexpected settings",
)

WIFI_PROFILE_DRIFT = FaultSpec(
    id="wifi_profile_drift",
    translation_key="hotspot_configuration",
    summary="The app-owned Wi-Fi hotspot profile has unexpected settings",
    template="The app-owned Wi-Fi hotspot profile has unexpected settings",
)

HOTSPOT_CREDENTIALS_MISSING = FaultSpec(
    id="hotspot_credentials_missing",
    translation_key="hotspot_configuration",
    summary="Wi-Fi hotspot credentials are not configured",
    template="Wi-Fi hotspot credentials are not configured",
)

WIFI_INSPECTION_WAITING = FaultSpec(
    id="wifi_inspection_waiting",
    summary="Waiting for NetworkManager Wi-Fi inspection",
    transient=True,
    template="NetworkManager Wi-Fi inspection is unavailable",
)

UPSTREAM_FAULTS: tuple[FaultSpec, ...] = (
    UPSTREAM_USB_ACCESS_UNAVAILABLE,
    WIFI_MANAGEMENT_OVERLAP,
    WIFI_CUSTODY_MANAGEMENT,
    WIFI_DEVICE_MISSING,
    WIFI_DEVICE_UNMANAGED,
    WIFI_RADIO_OFF,
    WIFI_RADIO_BLOCKED,
    WIFI_RADIO_INSPECTION_UNAVAILABLE,
    WIFI_DISPLACE_FAILED,
    LINEAGE_WIFI_DELETE_FAILED,
    HOTSPOT_AUTH_FAILED,
    HOTSPOT_TARGET_ABSENT,
    HOTSPOT_CONNECTING,
    WIFI_RESTORATION_INCOMPLETE,
    WIFI_RESTORATION_PENDING,
    UPSTREAM_FOREIGN_PROFILE,
    UPSTREAM_PROFILE_DRIFT,
    UPSTREAM_PROFILE_DRIFT_2,
    WIFI_PROFILE_DRIFT,
    HOTSPOT_CREDENTIALS_MISSING,
    WIFI_INSPECTION_WAITING,
)


PAIRING_FAULTS: dict[str, FaultSpec] = {
    "waiting_for_device": FaultSpec(
        id="upstream_waiting_for_device",
        summary="Waiting for a USB upstream device",
        transient=True,
    ),
    "waiting_for_hotspot": FaultSpec(
        id="upstream_waiting_for_hotspot",
        summary="Waiting for iPhone Personal Hotspot",
        transient=True,
    ),
    "waiting_for_carrier": FaultSpec(
        id="upstream_waiting_for_carrier",
        summary="Waiting for USB tethering carrier",
        transient=True,
    ),
    "waiting_for_profile": FaultSpec(
        id="upstream_waiting_for_profile",
        summary="Waiting for the NetworkManager USB profile",
        transient=True,
    ),
    "waiting_for_interface": FaultSpec(
        id="upstream_waiting_for_interface",
        summary="Waiting for the iPhone USB network interface",
        transient=True,
    ),
    "not_ready": FaultSpec(
        id="upstream_not_ready",
        summary="Upstream connectivity is not ready",
        transient=True,
    ),
    "waiting_for_trust": FaultSpec(
        id="upstream_waiting_for_trust",
        summary="Waiting for iPhone USB trust confirmation",
        transient=True,
    ),
    "waiting_for_unlock": FaultSpec(
        id="upstream_waiting_for_unlock",
        summary="Waiting for iPhone to be unlocked",
        transient=True,
    ),
    "daemon_failed": FaultSpec(
        id="upstream_daemon_failed",
        translation_key="upstream_configuration",
        summary="The iPhone USB pairing helper failed to start",
    ),
    "profile_failed": FaultSpec(
        id="upstream_profile_failed",
        translation_key="upstream_configuration",
        summary="The NetworkManager iPhone USB profile could not be configured",
    ),
    "profile_conflict": FaultSpec(
        id="upstream_profile_conflict",
        translation_key="upstream_configuration",
        summary="A different NetworkManager profile controls the USB upstream interface",
    ),
    "invalid_lease": FaultSpec(
        id="upstream_invalid_lease",
        translation_key="upstream_configuration",
        summary="The USB NetworkManager lease is invalid",
    ),
    "multiple_devices": FaultSpec(
        id="upstream_multiple_devices",
        translation_key="upstream_configuration",
        summary="Multiple USB upstream devices detected",
    ),
    "pairing_failed": FaultSpec(
        id="upstream_pairing_failed",
        translation_key="upstream_configuration",
        summary="iPhone USB pairing failed",
    ),
}
