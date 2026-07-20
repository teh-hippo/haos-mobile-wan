"""Production USB profile creation and inventory-read scenario."""

from __future__ import annotations

from app.nm_inventory import NmInventory
from app.nm_profile import NmProfile
from app.nm_profile_specs import USB_PROFILE_UUID, usb_profile_spec
from live_dbus import profile_exists
from live_tracing import TracingRun, require


def test_production_profile_and_inventory(run: TracingRun) -> None:
    profile = NmProfile(run, usb_profile_spec())
    profile.create()
    require(profile.inspect().state == "exact", "production USB profile is not exact")
    profiles = {record.uuid: record for record in NmInventory(run).profiles()}
    require(
        profiles[USB_PROFILE_UUID].connection_type == "802-3-ethernet",
        "inventory did not read the production profile",
    )
    profile.delete()
    require(not profile_exists(run, USB_PROFILE_UUID), "production profile remains")
