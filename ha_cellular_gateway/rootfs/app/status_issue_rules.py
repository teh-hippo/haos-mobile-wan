from __future__ import annotations

from collections.abc import Callable

Rule = tuple[Callable[[str], bool], str, str | None, str | None]


def _startswith(*prefixes: str) -> Callable[[str], bool]:
    return lambda error: error.startswith(prefixes)


def _contains(substring: str) -> Callable[[str], bool]:
    return lambda error: substring in error


def _equals(value: str) -> Callable[[str], bool]:
    return lambda error: error == value


ERROR_RULES: tuple[Rule, ...] = (
    (
        _startswith("Strict rp_filter is enabled on "),
        "strict_rp_filter_enabled",
        "host_configuration",
        "Strict rp_filter is enabled on a required interface",
    ),
    (
        _startswith("Cannot read rp_filter for "),
        "rp_filter_unavailable",
        "host_configuration",
        "The gateway could not read rp_filter on a required interface",
    ),
    (
        _startswith("Unexpected main-table default route:"),
        "unexpected_default_route",
        "host_configuration",
        "An unexpected main default route is present",
    ),
    (
        _startswith("Policy priority "),
        "policy_priority_conflict",
        "policy_configuration",
        "A required policy-routing priority is already in use",
    ),
    (
        _contains("already has a foreign policy rule"),
        "policy_foreign_rule",
        "policy_configuration",
        "A foreign policy rule is using the gateway routing table",
    ),
    (
        _contains("contains an unexpected route"),
        "policy_unexpected_route",
        "policy_configuration",
        "The gateway routing table contains an unexpected route",
    ),
    (
        _startswith("Required command is unavailable: "),
        "upstream_required_command_unavailable",
        "upstream_configuration",
        "A required iPhone USB command is not installed",
    ),
    (
        _startswith("Invalid app configuration: Hotspot "),
        "hotspot_configuration_failed",
        "hotspot_configuration",
        "The hotspot Wi-Fi profile could not be configured",
    ),
    (
        _startswith("Cannot read app configuration:", "Invalid app configuration:"),
        "app_configuration_unavailable",
        "host_configuration",
        "The app could not load a safe host configuration",
    ),
    (
        _startswith("Hotspot Wi-Fi provisioning failed:"),
        "hotspot_configuration_failed",
        "hotspot_configuration",
        "The hotspot Wi-Fi profile could not be configured",
    ),
    (
        _startswith("Safety inspection failed:"),
        "safety_inspection_failed",
        "host_configuration",
        "The gateway could not complete its safety inspection",
    ),
    (
        _startswith("Activation failed:"),
        "activation_failed",
        "host_configuration",
        "The gateway could not apply the requested network state",
    ),
    (
        _startswith("Auto-disable cleanup failed:"),
        "auto_disable_cleanup_failed",
        None,
        None,
    ),
    (_startswith("Auto-stop request failed:"), "auto_stop_request_failed", None, None),
    (
        _startswith("Auto-disable state persistence failed:"),
        "auto_disable_state_failed",
        None,
        None,
    ),
    (
        _startswith("Hotspot Wi-Fi deactivation failed:"),
        "hotspot_deactivation_failed",
        None,
        None,
    ),
    (
        _startswith("NetworkManager profile operation failed:"),
        "networkmanager_profile_failed",
        None,
        None,
    ),
    (
        _startswith("NetworkManager profile cleanup failed:"),
        "networkmanager_cleanup_failed",
        None,
        None,
    ),
    (
        _startswith("NetworkManager ownership journal failed:"),
        "networkmanager_journal_failed",
        None,
        None,
    ),
    (
        _startswith("Management interface changed from "),
        "management_interface_changed",
        "host_configuration",
        None,
    ),
    (
        _equals("Hotspot Wi-Fi interface is the management interface"),
        "hotspot_management_overlap",
        None,
        None,
    ),
)


def issue_from_rules(error: str) -> tuple[str, str | None, str] | None:
    for matches, issue_id, key, message in ERROR_RULES:
        if matches(error):
            return issue_id, key, message or error
    return None
