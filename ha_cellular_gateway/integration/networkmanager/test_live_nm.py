from __future__ import annotations

from app.command import CommandRunner
from live_dbus import delete_fixed_profiles
from live_link import teardown_active_links
from live_scenario_custody import test_custody_dhcp_and_cleanup
from live_scenario_inert import (
    test_generated_default_safety,
    test_inert_creation_controls,
)
from live_scenario_production import test_production_profile_and_inventory
from live_scenario_wifi_secret import test_wifi_marker_preserves_secret
from live_tracing import TracingRun, require


def test_nmcli_radio_output_shape() -> None:
    runner = CommandRunner()
    combined = runner.run(
        ["nmcli", "-g", "WIFI-HW,WIFI", "radio"],
        check=False,
    )
    require(combined.returncode == 0, "real nmcli radio query failed")
    rows = (combined.stdout or "").splitlines()
    require(
        len(rows) == 1 and ":" in rows[0],
        "real nmcli did not return one tabular multi-field row",
    )
    for field in ("WIFI-HW", "WIFI"):
        result = runner.run(["nmcli", "-g", field, "radio"], check=False)
        require(result.returncode == 0, f"real nmcli {field} query failed")
        require(
            len((result.stdout or "").splitlines()) == 1,
            f"real nmcli {field} query was not scalar",
        )


def main() -> None:
    test_nmcli_radio_output_shape()
    run = TracingRun()
    delete_fixed_profiles(run)
    try:
        test_production_profile_and_inventory(run)
        test_inert_creation_controls(run)
        test_generated_default_safety(run)
        test_custody_dhcp_and_cleanup(run)
        test_wifi_marker_preserves_secret(run)
        print("NetworkManager integration lab passed")
    finally:
        teardown_active_links(run)


if __name__ == "__main__":
    main()
