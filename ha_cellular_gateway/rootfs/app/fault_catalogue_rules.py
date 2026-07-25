"""Faults whose reported text carries a variable detail, matched by their head.

Order is significant. The first match wins, so a more specific entry must
precede any general one that would otherwise swallow it.
"""

from __future__ import annotations

from .faults import FaultSpec

RULE_FAULTS: tuple[FaultSpec, ...] = (
    FaultSpec(
        id="strict_rp_filter_enabled",
        translation_key="host_configuration",
        summary="Strict rp_filter is enabled on a required interface",
        prefixes=("Strict rp_filter is enabled on ",),
    ),
    FaultSpec(
        id="rp_filter_unavailable",
        translation_key="host_configuration",
        summary="The gateway could not read rp_filter on a required interface",
        prefixes=("Cannot read rp_filter for ",),
    ),
    FaultSpec(
        id="unexpected_default_route",
        translation_key="host_configuration",
        summary="An unexpected main default route is present",
        prefixes=("Unexpected main-table default route:",),
    ),
    FaultSpec(
        id="policy_priority_conflict",
        translation_key="policy_configuration",
        summary="A required policy-routing priority is already in use",
        prefixes=("Policy priority ",),
    ),
    FaultSpec(
        id="policy_foreign_rule",
        translation_key="policy_configuration",
        summary="A foreign policy rule is using the gateway routing table",
        contains=("already has a foreign policy rule",),
    ),
    FaultSpec(
        id="policy_unexpected_route",
        translation_key="policy_configuration",
        summary="The gateway routing table contains an unexpected route",
        contains=("contains an unexpected route",),
    ),
    FaultSpec(
        id="upstream_required_command_unavailable",
        translation_key="upstream_configuration",
        summary="A required iPhone USB command is not installed",
        prefixes=("Required command is unavailable: ",),
    ),
    FaultSpec(
        id="hotspot_configuration_failed",
        translation_key="hotspot_configuration",
        summary="The hotspot Wi-Fi profile could not be configured",
        prefixes=("Invalid app configuration: Hotspot ",),
    ),
    FaultSpec(
        id="app_configuration_unavailable",
        translation_key="host_configuration",
        summary="The app could not load a safe host configuration",
        prefixes=("Cannot read app configuration:", "Invalid app configuration:"),
    ),
    FaultSpec(
        id="hotspot_configuration_failed",
        translation_key="hotspot_configuration",
        summary="The hotspot Wi-Fi profile could not be configured",
        prefixes=("Hotspot Wi-Fi provisioning failed:",),
    ),
    FaultSpec(
        id="safety_inspection_failed",
        translation_key="host_configuration",
        summary="The gateway could not complete its safety inspection",
        prefixes=("Safety inspection failed:",),
    ),
    FaultSpec(
        id="activation_failed",
        translation_key="host_configuration",
        summary="The gateway could not apply the requested network state",
        prefixes=("Activation failed:",),
    ),
    FaultSpec(
        id="auto_disable_cleanup_failed", prefixes=("Auto-disable cleanup failed:",)
    ),
    FaultSpec(id="auto_stop_request_failed", prefixes=("Auto-stop request failed:",)),
    FaultSpec(
        id="auto_disable_state_failed",
        prefixes=("Auto-disable state persistence failed:",),
    ),
    FaultSpec(
        id="hotspot_deactivation_failed",
        prefixes=("Hotspot Wi-Fi deactivation failed:",),
    ),
    FaultSpec(
        id="networkmanager_profile_failed",
        prefixes=("NetworkManager profile operation failed:",),
    ),
    FaultSpec(
        id="networkmanager_cleanup_failed",
        prefixes=("NetworkManager profile cleanup failed:",),
    ),
    FaultSpec(
        id="networkmanager_journal_failed",
        prefixes=("NetworkManager ownership journal failed:",),
    ),
    FaultSpec(
        id="management_interface_changed",
        translation_key="host_configuration",
        prefixes=("Management interface changed from ",),
    ),
    FaultSpec(
        id="hotspot_management_overlap",
        template="Hotspot Wi-Fi interface is the management interface",
    ),
)
