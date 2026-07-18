from __future__ import annotations

from dataclasses import dataclass

from .command import RunCommand
from .nm_profile import normalise_setting


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
            "-t",
            "--separator",
            "|",
            "-f",
            "UUID,TYPE,NAME",
            "connection",
            "show",
            check=False,
        )
        if result.returncode != 0:
            return []
        records: list[ProfileRecord] = []
        for line in (result.stdout or "").splitlines():
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            uuid, connection_type, name = parts
            settings = self._binding_settings(uuid)
            records.append(
                ProfileRecord(
                    uuid=uuid,
                    connection_type=connection_type,
                    name=name,
                    interface_name=normalise_setting(
                        settings.get("connection.interface-name", "")
                    ),
                    match_driver=normalise_setting(
                        settings.get("match.driver", "")
                    ),
                    ssid=normalise_setting(
                        settings.get("802-11-wireless.ssid", "")
                    ),
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

    def _binding_settings(self, uuid: str) -> dict[str, str]:
        fields = (
            "connection.interface-name",
            "match.driver",
            "802-11-wireless.ssid",
            "ipv4.addresses",
        )
        result = self.run(
            "nmcli",
            "-g",
            ",".join(fields),
            "connection",
            "show",
            uuid,
            check=False,
        )
        if result.returncode != 0:
            return {}
        values = (result.stdout or "").splitlines()
        return {
            field: values[index].strip() if index < len(values) else ""
            for index, field in enumerate(fields)
        }
