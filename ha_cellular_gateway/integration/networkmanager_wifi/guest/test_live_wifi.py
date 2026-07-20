from __future__ import annotations

import os
import signal
import subprocess
import time

from app.command import CommandRunner
from app.config import GatewayConfig
from app.const import (
    GENERIC_USB,
    GENERIC_USB_WIFI_FALLBACK,
    WIFI_HOTSPOT,
)
from app.management import ManagementBaseline
from app.mobile_connection import MobileConnectionResolver
from app.networkmanager_wifi import NetworkManagerWifi
from app.nm_profile_specs import GENERIC_USB_PROFILE_UUID, WIFI_PROFILE_UUID
from app.upstream_generic_usb import GenericUsbUpstream
from app.wifi_custody import RADIO_HARD_OFF

FOREIGN_UUID = "4a229445-9e75-45a6-9a0a-8d9ea2a75a10"
PROFILE_FIELDS = (
    "connection.id",
    "connection.uuid",
    "connection.type",
    "connection.interface-name",
    "connection.autoconnect",
    "802-11-wireless.ssid",
    "ipv4.method",
    "ipv4.addresses",
    "ipv4.gateway",
)


def require(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class TracingRun:
    def __init__(self, interface: str) -> None:
        self.runner = CommandRunner()
        self.interface = interface
        self.commands: list[tuple[str, ...]] = []

    def __call__(
        self,
        *args: str,
        check: bool = True,
        timeout: int = 20,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(args)
        result = self.runner.run(list(args), check=check, timeout=timeout)
        if (
            len(args) >= 6
            and args[:2] == ("nmcli", "-g")
            and args[3:5] == ("device", "show")
            and args[5] == self.interface
            and args[2].split(",")[0] == "GENERAL.PATH"
        ):
            values = (result.stdout or "").splitlines()
            if not values or not values[0].strip(" -*"):
                identity = f"hwsim:{self.interface}"
                values = [identity, *values[1:]] if values else [identity]
                stdout = "\n".join(values) + "\n"
                return subprocess.CompletedProcess(
                    result.args,
                    result.returncode,
                    stdout,
                    result.stderr,
                )
        return result


def config(
    *,
    password: str | None = None,
    connection: str = WIFI_HOTSPOT,
) -> GatewayConfig:
    return GatewayConfig(
        auto_disable_minutes=0,
        mobile_connection=connection,
        upstream_interface=os.environ["LAB_CLIENT_INTERFACE"],
        upstream_address="172.20.10.4/28",
        upstream_gateway="172.20.10.1",
        hotspot_ssid=os.environ["LAB_SSID"],
        hotspot_password=password or os.environ["LAB_PSK"],
        downstream_mac="",
        downstream_address="192.168.80.1/24",
    )


def profile_exists(
    run: TracingRun,
    uuid: str = WIFI_PROFILE_UUID,
) -> bool:
    return (
        run(
            "nmcli",
            "-g",
            "connection.uuid",
            "connection",
            "show",
            uuid,
            check=False,
        ).returncode
        == 0
    )


def wait_for(predicate, message: str, seconds: float = 30) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.5)
    raise AssertionError(message)


def active_uuid(run: TracingRun) -> str:
    result = run(
        "nmcli",
        "-g",
        "GENERAL.CON-UUID",
        "device",
        "show",
        os.environ["LAB_CLIENT_INTERFACE"],
        check=False,
    )
    return (result.stdout or "").strip()


def profile_settings(run: TracingRun, uuid: str) -> tuple[str, ...]:
    result = run(
        "nmcli",
        "-g",
        ",".join(PROFILE_FIELDS),
        "connection",
        "show",
        uuid,
    )
    return tuple((result.stdout or "").splitlines())


def create_foreign_profile(run: TracingRun) -> tuple[str, ...]:
    interface = os.environ["LAB_CLIENT_INTERFACE"]
    run(
        "nmcli",
        "connection",
        "add",
        "type",
        "wifi",
        "con-name",
        "Foreign Wi-Fi",
        "connection.uuid",
        FOREIGN_UUID,
        "ifname",
        interface,
        "ssid",
        os.environ["LAB_SSID"],
    )
    run(
        "nmcli",
        "connection",
        "modify",
        "uuid",
        FOREIGN_UUID,
        "connection.autoconnect",
        "yes",
        "wifi-sec.key-mgmt",
        "wpa-psk",
        "wifi-sec.psk",
        os.environ["LAB_PSK"],
        "ipv4.method",
        "manual",
        "ipv4.addresses",
        "172.20.10.5/28",
        "ipv4.gateway",
        "172.20.10.1",
        "ipv6.method",
        "disabled",
    )
    run(
        "nmcli",
        "-w",
        "15",
        "connection",
        "up",
        "uuid",
        FOREIGN_UUID,
        "ifname",
        interface,
    )
    require(active_uuid(run) == FOREIGN_UUID, "foreign profile did not activate")
    return profile_settings(run, FOREIGN_UUID)


def wait_until_active(wifi: NetworkManagerWifi) -> None:
    result = wifi.inspect()
    deadline = time.monotonic() + 30
    while result.upstream is None and time.monotonic() < deadline:
        time.sleep(1)
        result = wifi.inspect()
    require(result.upstream is not None, f"Wi-Fi did not become active: {result.error}")


def stop_hostapd() -> None:
    with open(os.environ["LAB_HOSTAPD_PID_FILE"], encoding="utf-8") as stream:
        pid = int(stream.read())
    os.kill(pid, signal.SIGTERM)
    wait_for(
        lambda: not _process_exists(pid),
        "hostapd did not stop",
        seconds=10,
    )


def start_hostapd() -> None:
    try:
        os.unlink(os.environ["LAB_HOSTAPD_PID_FILE"])
    except FileNotFoundError:
        pass
    result = subprocess.run(
        [
            "ip",
            "netns",
            "exec",
            os.environ["LAB_AP_NAMESPACE"],
            "hostapd",
            "-B",
            "-P",
            os.environ["LAB_HOSTAPD_PID_FILE"],
            "-f",
            os.environ["LAB_HOSTAPD_LOG"],
            os.environ["LAB_HOSTAPD_CONFIG"],
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    require(result.returncode == 0, "hostapd did not restart")


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def target_visible(run: TracingRun) -> bool:
    interface = os.environ["LAB_CLIENT_INTERFACE"]
    run(
        "nmcli",
        "device",
        "wifi",
        "rescan",
        "ifname",
        interface,
        check=False,
    )
    result = run(
        "nmcli",
        "-g",
        "SSID",
        "device",
        "wifi",
        "list",
        "ifname",
        interface,
        "--rescan",
        "no",
        check=False,
    )
    return os.environ["LAB_SSID"] in (result.stdout or "").splitlines()


def management() -> ManagementBaseline:
    return ManagementBaseline(
        os.environ["LAB_MANAGEMENT_INTERFACE"],
        os.environ["LAB_MANAGEMENT_ADDRESS"],
    )


def generic_interface() -> str | None:
    root = "/sys/class/net"
    for name in os.listdir(root):
        driver = os.path.join(root, name, "device", "driver")
        if not os.path.exists(driver):
            continue
        if os.path.basename(os.path.realpath(driver)) in {
            "rndis_host",
            "cdc_ether",
            "cdc_ncm",
        }:
            return name
    return None


def bind_generic_usb() -> str:
    driver = os.environ["LAB_GENERIC_USB_DRIVER"]
    bind_id = os.environ["LAB_GENERIC_USB_BIND_ID"]
    with open(
        f"/sys/bus/usb/drivers/{driver}/bind",
        "w",
        encoding="utf-8",
    ) as stream:
        stream.write(bind_id)
    wait_for(lambda: generic_interface() is not None, "generic USB did not bind")
    interface = generic_interface()
    assert interface is not None
    return interface


def unbind_generic_usb() -> None:
    driver = os.environ["LAB_GENERIC_USB_DRIVER"]
    bind_id = os.environ["LAB_GENERIC_USB_BIND_ID"]
    with open(
        f"/sys/bus/usb/drivers/{driver}/unbind",
        "w",
        encoding="utf-8",
    ) as stream:
        stream.write(bind_id)
    wait_for(lambda: generic_interface() is None, "generic USB did not unbind")


def resolve_generic(
    usb: GenericUsbUpstream,
) -> object:
    resolved, errors = usb.resolve(management(), "downstream0")
    deadline = time.monotonic() + 30
    while resolved is None and time.monotonic() < deadline:
        time.sleep(1)
        resolved, errors = usb.resolve(management(), "downstream0")
    require(resolved is not None, f"generic USB did not become active: {errors}")
    return resolved


def legacy_control(run: TracingRun, wifi: NetworkManagerWifi) -> None:
    errors = wifi.claim(os.environ["LAB_MANAGEMENT_INTERFACE"])

    require(RADIO_HARD_OFF in errors, "v0.10.0 did not reproduce the false block")
    require(not profile_exists(run), "legacy code unexpectedly created Wi-Fi profile")
    require(
        ("nmcli", "-g", "WIFI-HW,WIFI", "radio") in run.commands,
        "legacy code did not execute the combined radio query",
    )


def fixed_control(run: TracingRun, wifi: NetworkManagerWifi) -> None:
    foreign_before = create_foreign_profile(run)
    errors = wifi.claim(os.environ["LAB_MANAGEMENT_INTERFACE"])
    require(not errors, f"Wi-Fi claim failed: {errors}")
    require(profile_exists(run), "fixed code did not create the Wi-Fi profile")
    require(active_uuid(run) != FOREIGN_UUID, "foreign profile remains active")

    wait_until_active(wifi)
    require(
        ("nmcli", "-g", "WIFI-HW", "radio") in run.commands,
        "fixed code did not read the hardware radio field",
    )
    require(
        ("nmcli", "-g", "WIFI", "radio") in run.commands,
        "fixed code did not read the software radio field",
    )
    require(
        ("nmcli", "-g", "WIFI-HW,WIFI", "radio") not in run.commands,
        "fixed code still used the combined radio query",
    )

    errors = wifi.release(os.environ["LAB_MANAGEMENT_INTERFACE"])
    require(not errors, f"Wi-Fi release failed: {errors}")
    require(not profile_exists(run), "app Wi-Fi profile remains after release")
    require(active_uuid(run) == FOREIGN_UUID, "foreign profile was not restored")
    require(
        profile_settings(run, FOREIGN_UUID) == foreign_before,
        "foreign profile definition changed",
    )
    run("nmcli", "connection", "delete", "uuid", FOREIGN_UUID)

    wrong = NetworkManagerWifi(config(password="lab-incorrect-psk"), run)
    errors = wrong.claim(os.environ["LAB_MANAGEMENT_INTERFACE"])
    require(not errors, f"wrong-PSK claim failed: {errors}")
    result = wrong.inspect()
    deadline = time.monotonic() + 20
    while result.state != "auth_failed" and time.monotonic() < deadline:
        time.sleep(1)
        result = wrong.inspect()
    require(result.state == "auth_failed", "wrong PSK was not classified")
    require(
        not wrong.release(os.environ["LAB_MANAGEMENT_INTERFACE"]),
        "wrong-PSK release failed",
    )

    restored = NetworkManagerWifi(config(), run)
    require(
        not restored.claim(os.environ["LAB_MANAGEMENT_INTERFACE"]),
        "target-loss claim failed",
    )
    wait_until_active(restored)
    stop_hostapd()
    wait_for(
        lambda: not target_visible(run),
        "target SSID remained cached after access-point loss",
        seconds=60,
    )
    wait_for(
        lambda: active_uuid(run) != WIFI_PROFILE_UUID,
        "NetworkManager kept the lost access point active",
        seconds=20,
    )
    result = restored.inspect()
    require(result.upstream is None, "Wi-Fi stayed active after target loss")
    start_hostapd()
    wait_for(
        lambda: target_visible(run),
        "target SSID did not return",
        seconds=20,
    )
    wait_until_active(restored)
    require(
        not restored.release(os.environ["LAB_MANAGEMENT_INTERFACE"]),
        "target-return release failed",
    )

    fallback_config = config(connection=GENERIC_USB_WIFI_FALLBACK)
    generic = GenericUsbUpstream(fallback_config, run)
    generic.nm.profile.create()
    interface = bind_generic_usb()
    require(
        os.path.basename(os.path.realpath(f"/sys/class/net/{interface}/device/driver"))
        == "cdc_ether",
        "QEMU generic USB did not bind with cdc_ether",
    )
    resolved = resolve_generic(generic)
    require(resolved.connection == GENERIC_USB, "generic USB-only selection failed")
    require(profile_exists(run, GENERIC_USB_PROFILE_UUID), "generic profile missing")

    fallback_wifi = NetworkManagerWifi(fallback_config, run)
    require(
        not fallback_wifi.claim(os.environ["LAB_MANAGEMENT_INTERFACE"]),
        "generic fallback Wi-Fi claim failed",
    )
    wait_until_active(fallback_wifi)
    resolver = MobileConnectionResolver(
        fallback_config,
        generic,
        fallback_wifi,
    )
    selected = resolver.resolve(management(), "downstream0")
    require(
        selected.upstream is not None and selected.upstream.connection == GENERIC_USB,
        "generic USB was not preferred over Wi-Fi",
    )

    unbind_generic_usb()
    selected = resolver.resolve(management(), "downstream0")
    require(
        selected.upstream is not None
        and selected.upstream.connection == WIFI_HOTSPOT
        and selected.fallback_active,
        "Wi-Fi was not promoted after generic USB removal",
    )

    bind_generic_usb()
    deadline = time.monotonic() + 30
    selected = resolver.resolve(management(), "downstream0")
    while (
        selected.upstream is None or selected.upstream.connection != GENERIC_USB
    ) and time.monotonic() < deadline:
        time.sleep(1)
        selected = resolver.resolve(management(), "downstream0")
    require(
        selected.upstream is not None and selected.upstream.connection == GENERIC_USB,
        "generic USB preference did not return",
    )

    require(
        not fallback_wifi.release(os.environ["LAB_MANAGEMENT_INTERFACE"]),
        "generic fallback Wi-Fi release failed",
    )
    generic.nm.release_profile()
    generic.cleanup()
    require(
        not profile_exists(run, GENERIC_USB_PROFILE_UUID),
        "generic USB profile remains after cleanup",
    )


def main() -> None:
    run = TracingRun(os.environ["LAB_CLIENT_INTERFACE"])
    wifi = NetworkManagerWifi(config(), run)
    if os.environ["LAB_EXPECT"] == "legacy":
        legacy_control(run, wifi)
    else:
        fixed_control(run, wifi)


if __name__ == "__main__":
    main()
