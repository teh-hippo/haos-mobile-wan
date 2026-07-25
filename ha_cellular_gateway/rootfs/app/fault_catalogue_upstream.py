"""Faults reported by the mobile upstream, plus the iPhone pairing states."""

from __future__ import annotations

from .faults import FaultSpec

UPSTREAM_FAULTS: tuple[FaultSpec, ...] = (
    FaultSpec(
        id="upstream_usb_access_unavailable",
        translation_key="upstream_configuration",
        summary="USB device access is unavailable; enable the app USB permission",
        exact=("USB device access is unavailable; enable the app usb permission",),
    ),
    FaultSpec(
        id="wifi_management_overlap",
        translation_key="hotspot_configuration",
        summary="The Wi-Fi upstream is the management interface",
        exact=("Wi-Fi upstream is the management interface",),
    ),
    FaultSpec(
        id="wifi_custody_management",
        translation_key="hotspot_configuration",
        summary="The dedicated Wi-Fi adapter is the management interface",
        exact=("The dedicated Wi-Fi adapter is the management interface",),
    ),
    FaultSpec(
        id="wifi_device_missing",
        translation_key="hotspot_configuration",
        summary="The dedicated Wi-Fi adapter is not present",
        exact=("The dedicated Wi-Fi adapter is not present",),
    ),
    FaultSpec(
        id="wifi_device_unmanaged",
        translation_key="hotspot_configuration",
        summary="NetworkManager does not manage the dedicated Wi-Fi adapter",
        exact=("NetworkManager does not manage the dedicated Wi-Fi adapter",),
    ),
    FaultSpec(
        id="wifi_radio_off",
        translation_key="hotspot_configuration",
        summary="The Wi-Fi radio is turned off",
        exact=("The Wi-Fi radio is turned off",),
    ),
    FaultSpec(
        id="wifi_radio_blocked",
        translation_key="hotspot_configuration",
        summary="The Wi-Fi radio is hardware-blocked",
        exact=("The Wi-Fi radio is hardware-blocked",),
    ),
    FaultSpec(
        id="wifi_radio_inspection_unavailable",
        summary="NetworkManager Wi-Fi radio inspection is unavailable",
        exact=("NetworkManager Wi-Fi radio inspection is unavailable",),
    ),
    FaultSpec(
        id="wifi_displace_failed",
        translation_key="hotspot_configuration",
        summary="A foreign Wi-Fi connection still controls the dedicated adapter",
        exact=("A foreign Wi-Fi connection still controls the dedicated adapter",),
    ),
    FaultSpec(
        id="lineage_wifi_delete_failed",
        translation_key="hotspot_configuration",
        summary="A legacy Supervisor Wi-Fi profile could not be removed",
        exact=("A legacy Supervisor Wi-Fi profile could not be removed",),
    ),
    FaultSpec(
        id="hotspot_auth_failed",
        translation_key="hotspot_configuration",
        summary="The hotspot rejected the configured Wi-Fi password",
        exact=("The hotspot rejected the configured Wi-Fi password",),
    ),
    FaultSpec(
        id="hotspot_target_absent",
        summary="The hotspot network is not currently visible",
        transient=True,
        exact=("The hotspot network is not currently visible",),
    ),
    FaultSpec(
        id="hotspot_connecting",
        summary="Associating with the hotspot network",
        transient=True,
        exact=("Associating with the hotspot network",),
    ),
    FaultSpec(
        id="wifi_restoration_incomplete",
        translation_key="hotspot_configuration",
        summary="The dedicated Wi-Fi adapter runtime state was not fully restored",
        exact=("Wi-Fi adapter runtime restoration is incomplete",),
    ),
    FaultSpec(
        id="wifi_restoration_pending",
        summary="The dedicated Wi-Fi adapter runtime restoration is pending",
        transient=True,
        exact=("The marked Wi-Fi adapter runtime restoration is pending",),
    ),
    FaultSpec(
        id="upstream_foreign_profile",
        translation_key="upstream_configuration",
        summary="A foreign NetworkManager profile can control iPhone USB",
        exact=("iPhone USB has a foreign NetworkManager profile",),
    ),
    FaultSpec(
        id="upstream_profile_drift",
        translation_key="upstream_configuration",
        summary="The app-owned iPhone USB profile has unexpected settings",
        exact=("The app-owned iPhone USB profile has unexpected settings",),
    ),
    FaultSpec(
        id="upstream_profile_drift",
        translation_key="upstream_configuration",
        summary="The app-owned generic USB profile has unexpected settings",
        exact=("The app-owned generic USB profile has unexpected settings",),
    ),
    FaultSpec(
        id="wifi_profile_drift",
        translation_key="hotspot_configuration",
        summary="The app-owned Wi-Fi hotspot profile has unexpected settings",
        exact=("The app-owned Wi-Fi hotspot profile has unexpected settings",),
    ),
    FaultSpec(
        id="hotspot_credentials_missing",
        translation_key="hotspot_configuration",
        summary="Wi-Fi hotspot credentials are not configured",
        exact=("Wi-Fi hotspot credentials are not configured",),
    ),
    FaultSpec(
        id="wifi_inspection_waiting",
        summary="Waiting for NetworkManager Wi-Fi inspection",
        transient=True,
        exact=("NetworkManager Wi-Fi inspection is unavailable",),
    ),
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
