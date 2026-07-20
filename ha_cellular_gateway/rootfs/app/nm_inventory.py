from __future__ import annotations

from dataclasses import dataclass

from .command import RunCommand
from .errors import GatewayError
from .nm_profile import normalise_setting

PROFILE_FIELDS = (
    "connection.type",
    "connection.id",
    "connection.interface-name",
    "match.driver",
    "802-11-wireless.ssid",
    "ipv4.addresses",
)


@dataclass(frozen=True)
class ProfileRecord:
    uuid: str
    connection_type: str
    name: str
    interface_name: str
    match_driver: str
    ssid: str
    ipv4_addresses: str


class NmInventory:
    def __init__(self, run: RunCommand) -> None:
        self.run = run

    def profiles(self) -> list[ProfileRecord]:
        result = self.run(
            "nmcli",
            "--escape",
            "no",
            "-g",
            "UUID",
            "connection",
            "show",
            check=False,
        )
        if result.returncode != 0:
            raise GatewayError("Cannot inspect NetworkManager profiles")
        records: list[ProfileRecord] = []
        for uuid in (result.stdout or "").splitlines():
            uuid = uuid.strip()
            if not uuid:
                continue
            settings = self._profile_settings(uuid)
            records.append(
                ProfileRecord(
                    uuid=uuid,
                    connection_type=normalise_setting(
                        settings.get("connection.type", "")
                    ),
                    name=normalise_setting(settings.get("connection.id", "")),
                    interface_name=normalise_setting(
                        settings.get("connection.interface-name", "")
                    ),
                    match_driver=normalise_setting(settings.get("match.driver", "")),
                    ssid=normalise_setting(settings.get("802-11-wireless.ssid", "")),
                    ipv4_addresses=normalise_setting(
                        settings.get("ipv4.addresses", "")
                    ),
                )
            )
        return records

    def foreign_wifi_profiles(
        self,
        interface: str,
        *,
        allowed_uuid: str,
    ) -> list[ProfileRecord]:
        return [
            profile
            for profile in self.profiles()
            if profile.uuid != allowed_uuid
            and profile.connection_type == "802-11-wireless"
            and profile.interface_name in {"", interface}
        ]

    def foreign_ipheth_profiles(
        self,
        *,
        allowed_uuids: set[str],
    ) -> list[ProfileRecord]:
        return [
            profile
            for profile in self.profiles()
            if profile.uuid not in allowed_uuids
            and "ipheth" in profile.match_driver.split(",")
        ]

    def foreign_wired_profiles(
        self,
        interface: str,
        *,
        drivers: set[str],
        allowed_uuids: set[str],
    ) -> list[ProfileRecord]:
        return [
            profile
            for profile in self.profiles()
            if profile.uuid not in allowed_uuids
            and profile.connection_type == "802-3-ethernet"
            and (
                profile.interface_name == interface
                or bool(drivers & set(profile.match_driver.split(",")))
            )
        ]

    def _profile_settings(self, uuid: str) -> dict[str, str]:
        result = self.run(
            "nmcli",
            "--escape",
            "no",
            "-g",
            ",".join(PROFILE_FIELDS),
            "connection",
            "show",
            uuid,
            check=False,
        )
        if result.returncode != 0:
            raise GatewayError("Cannot inspect NetworkManager profile bindings")
        values = (result.stdout or "").splitlines()
        return {
            field: values[index].strip() if index < len(values) else ""
            for index, field in enumerate(PROFILE_FIELDS)
        }
