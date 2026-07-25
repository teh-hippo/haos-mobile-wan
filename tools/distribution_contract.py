"""Check that what ships is shaped the way the add-on is documented to be.

These assertions used to live in a YAML heredoc, so ruff, mypy and the test
suite never saw the code guarding the app's privileges, its base image and its
AppArmor profile. They are ordinary Python here, and tested.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from tools.app_metadata import config

APPARMOR_PATH = Path("ha_cellular_gateway/apparmor.txt")
DOCKERFILE_PATH = Path("ha_cellular_gateway/Dockerfile")
BASE_IMAGE_PREFIX = "FROM ghcr.io/home-assistant/base:"

REQUIRED_FILES = (
    Path("ha_cellular_gateway/DOCS.md"),
    Path("ha_cellular_gateway/translations/en.yaml"),
)

# The app asks for the narrowest privileges that still let it move routes and
# firewall rules. Widening any of these is a security decision, not a tidy-up.
EXPECTED_CONFIG: dict[str, object] = {
    "arch": ["aarch64"],
    "host_network": True,
    "host_dbus": True,
    "hassio_api": True,
    "hassio_role": "manager",
    "usb": True,
    "privileged": ["NET_ADMIN", "NET_RAW"],
}
DISALLOWED_CONFIG = ("apparmor",)
OPTIONAL_FALSE_CONFIG = ("full_access", "udev")

REQUIRED_PROFILE_RULES = (
    "capability net_admin,",
    "capability net_raw,",
    "/run/dbus/system_bus_socket rw,",
    "peer=(name=org.freedesktop.NetworkManager),",
    "/run/ha-cellgw/** rwk,",
    "/run/usbmuxd rw,",
    "/run/usbmuxd/** rwk,",
    "/var/run/usbmuxd rw,",
    "/var/lib/lockdown/** rwk,",
    "/proc/sys/net/ipv4/** r,",
    "/dev/bus/usb/** rw,",
    "/usr/bin/nmcli rix,",
    "/sys/bus/usb/devices/ r,",
    "/sys/bus/usb/devices/** r,",
    "/sys/bus/usb/drivers/ipheth/** r,",
    "/sys/bus/usb/drivers/rndis_host/** r,",
    "/sys/bus/usb/drivers/cdc_ether/** r,",
    "/sys/bus/usb/drivers/cdc_ncm/** r,",
    "/sys/module/ipheth/** r,",
)
# Broad globs would defeat the point of confining the app at all, and the
# udhcpc client was replaced by NetworkManager leases.
FORBIDDEN_PROFILE_RULES = (
    "complain",
    "/run/**",
    "/proc/**",
    "/sys/bus/usb/**",
    "/sys/module/**",
    "/usr/sbin/conntrack",
    "/sbin/udhcpc",
    "udhcpc.script",
)


def serialisation_errors(root: Path = Path()) -> list[str]:
    errors: list[str] = []
    for path in sorted(root.rglob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            errors.append(f"{path} is not valid JSON: {error}")
    for pattern in ("*.yaml", "*.yml"):
        for path in sorted(root.rglob(pattern)):
            try:
                yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as error:
                errors.append(f"{path} is not valid YAML: {error}")
    return errors


def app_errors(app: dict[str, object]) -> list[str]:
    errors = [
        f"config.yaml {key} must be {expected!r}, found {app.get(key)!r}"
        for key, expected in EXPECTED_CONFIG.items()
        if app.get(key) != expected
    ]
    errors.extend(
        f"config.yaml must not set {key}" for key in DISALLOWED_CONFIG if key in app
    )
    errors.extend(
        f"config.yaml {key} must be absent or false"
        for key in OPTIONAL_FALSE_CONFIG
        if app.get(key) not in (None, False)
    )
    return errors


def image_errors(dockerfile: str) -> list[str]:
    errors: list[str] = []
    if "ARG BUILD_FROM" in dockerfile:
        errors.append("Dockerfile must pin its base image rather than take BUILD_FROM")
    if not dockerfile.startswith(BASE_IMAGE_PREFIX):
        errors.append(f"Dockerfile must start with {BASE_IMAGE_PREFIX}")
    return errors


def profile_errors(profile: str) -> list[str]:
    errors = [
        f"AppArmor profile is missing {rule!r}"
        for rule in REQUIRED_PROFILE_RULES
        if rule not in profile
    ]
    errors.extend(
        f"AppArmor profile must not contain {rule!r}"
        for rule in FORBIDDEN_PROFILE_RULES
        if rule in profile
    )
    return errors


def violations(root: Path = Path()) -> list[str]:
    errors = serialisation_errors(root)
    errors.extend(app_errors(config()))
    errors.extend(
        f"{path} is missing" for path in REQUIRED_FILES if not (root / path).exists()
    )
    errors.extend(image_errors((root / DOCKERFILE_PATH).read_text(encoding="utf-8")))
    errors.extend(profile_errors((root / APPARMOR_PATH).read_text(encoding="utf-8")))
    return errors


def main() -> int:
    errors = violations()
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Distribution contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
