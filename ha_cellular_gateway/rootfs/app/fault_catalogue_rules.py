"""Faults whose reported text carries a variable detail, matched by their head.

Order is significant. The first match wins, so a more specific entry must
precede any general one that would otherwise swallow it.
"""

from __future__ import annotations

from .faults import FaultSpec

STRICT_RP_FILTER_ENABLED = FaultSpec(
    id="strict_rp_filter_enabled",
    translation_key="host_configuration",
    summary="Strict rp_filter is enabled on a required interface",
    template="Strict rp_filter is enabled on {interface}",
)

RP_FILTER_UNAVAILABLE = FaultSpec(
    id="rp_filter_unavailable",
    translation_key="host_configuration",
    summary="The gateway could not read rp_filter on a required interface",
    template="Cannot read rp_filter for {interface}",
)

UNEXPECTED_DEFAULT_ROUTE = FaultSpec(
    id="unexpected_default_route",
    translation_key="host_configuration",
    summary="An unexpected main default route is present",
    template="Unexpected main-table default route: {detail}",
    prefixes=("Unexpected main-table default route:",),
)

POLICY_PRIORITY_CONFLICT = FaultSpec(
    id="policy_priority_conflict",
    translation_key="policy_configuration",
    summary="A required policy-routing priority is already in use",
    template="Policy priority {priority} is already in use",
)

POLICY_FOREIGN_RULE = FaultSpec(
    id="policy_foreign_rule",
    translation_key="policy_configuration",
    summary="A foreign policy rule is using the gateway routing table",
    contains=("already has a foreign policy rule",),
)

POLICY_UNEXPECTED_ROUTE = FaultSpec(
    id="policy_unexpected_route",
    translation_key="policy_configuration",
    summary="The gateway routing table contains an unexpected route",
    contains=("contains an unexpected route",),
)

UPSTREAM_REQUIRED_COMMAND_UNAVAILABLE = FaultSpec(
    id="upstream_required_command_unavailable",
    translation_key="upstream_configuration",
    summary="A required iPhone USB command is not installed",
    template="Required command is unavailable: {command}",
)

HOTSPOT_CONFIGURATION_FAILED = FaultSpec(
    id="hotspot_configuration_failed",
    translation_key="hotspot_configuration",
    summary="The hotspot Wi-Fi profile could not be configured",
    prefixes=(
        "Invalid app configuration: Hotspot ",
        "Hotspot Wi-Fi provisioning failed:",
    ),
)

APP_CONFIGURATION_UNAVAILABLE = FaultSpec(
    id="app_configuration_unavailable",
    translation_key="host_configuration",
    summary="The app could not load a safe host configuration",
    prefixes=("Cannot read app configuration:", "Invalid app configuration:"),
)

SAFETY_INSPECTION_FAILED = FaultSpec(
    id="safety_inspection_failed",
    translation_key="host_configuration",
    summary="The gateway could not complete its safety inspection",
    template="Safety inspection failed: {error}",
    prefixes=("Safety inspection failed:",),
)

ACTIVATION_FAILED = FaultSpec(
    id="activation_failed",
    translation_key="host_configuration",
    summary="The gateway could not apply the requested network state",
    template="Activation failed: {error}",
    prefixes=("Activation failed:",),
)

AUTO_DISABLE_CLEANUP_FAILED = FaultSpec(
    id="auto_disable_cleanup_failed",
    template="Auto-disable cleanup failed: {error}",
    prefixes=("Auto-disable cleanup failed:",),
)

AUTO_STOP_REQUEST_FAILED = FaultSpec(
    id="auto_stop_request_failed",
    template="Auto-stop request failed: {error}",
    prefixes=("Auto-stop request failed:",),
)

AUTO_DISABLE_STATE_FAILED = FaultSpec(
    id="auto_disable_state_failed",
    template="Auto-disable state persistence failed: {error}",
    prefixes=("Auto-disable state persistence failed:",),
)

HOTSPOT_DEACTIVATION_FAILED = FaultSpec(
    id="hotspot_deactivation_failed",
    prefixes=("Hotspot Wi-Fi deactivation failed:",),
)

NETWORKMANAGER_PROFILE_FAILED = FaultSpec(
    id="networkmanager_profile_failed",
    template="NetworkManager profile operation failed: {error}",
    prefixes=("NetworkManager profile operation failed:",),
)

NETWORKMANAGER_CLEANUP_FAILED = FaultSpec(
    id="networkmanager_cleanup_failed",
    template="NetworkManager profile cleanup failed: {error}",
    prefixes=("NetworkManager profile cleanup failed:",),
)

NETWORKMANAGER_JOURNAL_FAILED = FaultSpec(
    id="networkmanager_journal_failed",
    template="NetworkManager ownership journal failed: {error}",
    prefixes=("NetworkManager ownership journal failed:",),
)

MANAGEMENT_INTERFACE_CHANGED = FaultSpec(
    id="management_interface_changed",
    translation_key="host_configuration",
    prefixes=("Management interface changed from ",),
)

HOTSPOT_MANAGEMENT_OVERLAP = FaultSpec(
    id="hotspot_management_overlap",
    template="Hotspot Wi-Fi interface is the management interface",
)

# Order is significant: the first match wins.
RULE_FAULTS: tuple[FaultSpec, ...] = (
    STRICT_RP_FILTER_ENABLED,
    RP_FILTER_UNAVAILABLE,
    UNEXPECTED_DEFAULT_ROUTE,
    POLICY_PRIORITY_CONFLICT,
    POLICY_FOREIGN_RULE,
    POLICY_UNEXPECTED_ROUTE,
    UPSTREAM_REQUIRED_COMMAND_UNAVAILABLE,
    HOTSPOT_CONFIGURATION_FAILED,
    APP_CONFIGURATION_UNAVAILABLE,
    SAFETY_INSPECTION_FAILED,
    ACTIVATION_FAILED,
    AUTO_DISABLE_CLEANUP_FAILED,
    AUTO_STOP_REQUEST_FAILED,
    AUTO_DISABLE_STATE_FAILED,
    HOTSPOT_DEACTIVATION_FAILED,
    NETWORKMANAGER_PROFILE_FAILED,
    NETWORKMANAGER_CLEANUP_FAILED,
    NETWORKMANAGER_JOURNAL_FAILED,
    MANAGEMENT_INTERFACE_CHANGED,
    HOTSPOT_MANAGEMENT_OVERLAP,
)
