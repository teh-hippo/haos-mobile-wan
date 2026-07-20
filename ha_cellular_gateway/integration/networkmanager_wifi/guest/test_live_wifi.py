"""Entry point for the QEMU hwsim Wi-Fi integration lab.

Runs the legacy control-path regression for the pre-fix build, or, for the
fixed build, the Wi-Fi custody/restoration scenarios followed by the
fallback/generic USB scenario in the exact sequence production behaviour
must hold.
"""

from __future__ import annotations

import os

from app.networkmanager_wifi import NetworkManagerWifi
from guest_legacy import legacy_control
from guest_scenario_fallback import generic_usb_and_fallback
from guest_scenario_wifi import (
    custody_and_restoration,
    target_loss_and_recovery,
    wrong_psk_rejection,
)
from guest_tracing import TracingRun, config


def fixed_control(run: TracingRun, wifi: NetworkManagerWifi) -> None:
    custody_and_restoration(run, wifi)
    wrong_psk_rejection(run)
    target_loss_and_recovery(run)
    generic_usb_and_fallback(run)


def main() -> None:
    run = TracingRun(os.environ["LAB_CLIENT_INTERFACE"])
    wifi = NetworkManagerWifi(config(), run)
    if os.environ["LAB_EXPECT"] == "legacy":
        legacy_control(run, wifi)
    else:
        fixed_control(run, wifi)


if __name__ == "__main__":
    main()
