"""NetworkManager profile, device, and DHCP state for the fake command runner.

Models the subset of ``nmcli`` behaviour the app depends on: connection
profiles, device activation/state, DHCP auto-activation and lease
install/teardown, and Wi-Fi radio/scan state. Activating a profile or
installing a DHCP lease also updates interface addressing and the main
routing table, so this state composes a ``RouteInterfaceState`` rather than
duplicating that bookkeeping.
"""

from __future__ import annotations

from ipaddress import ip_interface
from typing import cast

from .process import Result
from .runner_routes import Address, RouteInterfaceState


class NetworkManagerState:
    def __init__(self, routes: RouteInterfaceState) -> None:
        self.routes = routes
        self.nm_profiles: dict[str, dict[str, str]] = {}
        self.nm_active: dict[str, str] = {}
        self.nm_routes: dict[int, list[dict[str, object]]] = {}
        self.nm_auto_activate = True
        # Interfaces that model a carrier-up device with a DHCP server ready to
        # lease, keyed to the offered {address, prefix, gateway}. A NetworkManager
        # connection added without connection.autoconnect=no auto-activates onto a
        # matching device and installs its DHCP routes, reproducing the real leak.
        self.nm_dhcp: dict[str, dict[str, object]] = {}
        # Interface an ethernet profile added with `ifname *` binds to, mirroring
        # the iPhone ipheth device that has no stable interface name.
        self.nm_wildcard_bind: str | None = None
        # DHCP leases the fake installed per profile uuid, so deactivate/delete
        # tears the lease and its routes down exactly as NetworkManager does.
        self.nm_dhcp_leases: dict[str, dict[str, object]] = {}
        self.nm_delete_fail = False
        self.nm_auth_failure = False
        self.nm_up_failures: set[str] = set()
        self.nm_path = {
            "end0": "platform-fd580000.ethernet",
            "wlan0": "platform-fe300000.mmcnr",
        }
        self.nm_managed = {"end0": True, "wlan0": True}
        self.nm_device_autoconnect = {"end0": True, "wlan0": True}
        self.nm_device_state = {"end0": "100 (connected)", "wlan0": "30 (disconnected)"}
        self.nm_device_reason = {"end0": "", "wlan0": ""}
        self.nm_radio_software = True
        self.nm_radio_hardware = True
        self.nm_radio_query_fail = False
        self.nm_wifi_cache: dict[str, set[str]] = {}

    def dispatch(self, args: list[str]) -> Result | None:
        device_result = self._device_dispatch(args)
        if device_result is not None:
            return device_result
        if args == ["nmcli", "--escape", "no", "-g", "UUID", "connection", "show"]:
            lines = list(self.nm_profiles)
            return Result(stdout="\n".join(lines) + ("\n" if lines else ""))
        if args[:4] == ["nmcli", "--escape", "no", "-g"] and args[5:7] == [
            "connection",
            "show",
        ]:
            return self._profile_fields(args[4].split(","), args[-1])
        if args[:3] == ["nmcli", "--show-secrets", "-g"]:
            return self._profile_fields(args[3].split(","), args[-1])
        if args[:2] == ["nmcli", "-g"] and args[3:5] == ["connection", "show"]:
            return self._profile_fields(args[2].split(","), args[-1])
        if args[:3] == ["nmcli", "connection", "add"]:
            return self._connection_add(args[3:])
        if args[:3] == ["nmcli", "connection", "modify"]:
            return self._connection_modify(args)
        if args[:4] == ["nmcli", "connection", "down", "uuid"]:
            return self._connection_down(args[4])
        if args[:4] == ["nmcli", "connection", "delete", "uuid"]:
            return self._connection_delete(args[4])
        if args[:3] == ["nmcli", "-g", "GENERAL.CON-UUID"]:
            return Result(stdout=self.nm_active.get(args[-1], "") + "\n")
        if args[:3] == ["nmcli", "-g", "IP4.ADDRESS"]:
            return self._ip4_address(args[-1])
        return None

    def _profile_fields(self, fields: list[str], uuid: str) -> Result:
        profile = self.nm_profiles.get(uuid)
        if profile is None:
            return Result(returncode=10)
        return Result(
            stdout="\n".join(profile.get(field, "") for field in fields) + "\n"
        )

    def _connection_add(self, pairs: list[str]) -> Result:
        add_fields = dict(zip(pairs[::2], pairs[1::2]))
        uuid = add_fields["connection.uuid"]
        kind = add_fields["type"]
        profile = {
            "connection.uuid": uuid,
            "connection.id": add_fields["con-name"],
            "connection.type": (
                "802-3-ethernet" if kind == "ethernet" else "802-11-wireless"
            ),
        }
        profile.update({key: value for key, value in add_fields.items() if "." in key})
        if "ssid" in add_fields:
            profile["802-11-wireless.ssid"] = add_fields["ssid"]
        ifname = add_fields.get("ifname", "")
        profile["__bind_iface"] = (
            ifname if ifname not in {"", "*"} else (self.nm_wildcard_bind or "")
        )
        self.nm_profiles[uuid] = profile
        if add_fields.get("connection.autoconnect", "yes") != "no":
            self._autoactivate(uuid)
        return Result()

    def _connection_modify(self, args: list[str]) -> Result:
        profile = self.nm_profiles[args[3]]
        pairs = args[4:]
        for index in range(0, len(pairs), 2):
            profile[pairs[index]] = pairs[index + 1]
        return Result()

    def _connection_down(self, uuid: str) -> Result:
        for interface, active_uuid in list(self.nm_active.items()):
            if active_uuid == uuid:
                del self.nm_active[interface]
        self._teardown_lease(uuid)
        return Result()

    def _connection_delete(self, uuid: str) -> Result:
        if self.nm_delete_fail:
            return Result(returncode=1)
        for interface, active_uuid in list(self.nm_active.items()):
            if active_uuid == uuid:
                del self.nm_active[interface]
        self._teardown_lease(uuid)
        self.nm_profiles.pop(uuid, None)
        return Result()

    def _ip4_address(self, interface: str) -> Result:
        configured = self.routes.get_address(interface)
        if configured is None:
            return Result(stdout="\n")
        addresses = configured if isinstance(configured, list) else [configured]
        return Result(
            stdout="\n".join(f"{address}/{prefix}" for address, prefix in addresses)
            + "\n"
        )

    def _device_dispatch(self, args: list[str]) -> Result | None:
        if (
            args[:2] == ["nmcli", "-g"]
            and args[3:5] == ["device", "show"]
            and all(field.startswith("GENERAL.") for field in args[2].split(","))
        ):
            return self._device_show(args[2].split(","), args[-1])
        if args == ["nmcli", "-g", "DEVICE", "device", "status"]:
            return Result(stdout="\n".join(self.nm_path) + "\n")
        if args == ["nmcli", "-g", "WIFI-HW,WIFI", "radio"]:
            return Result(returncode=2, stderr="unsupported combined radio query")
        if args == ["nmcli", "-g", "WIFI-HW", "radio"]:
            if self.nm_radio_query_fail:
                return Result(returncode=1)
            value = "enabled" if self.nm_radio_hardware else "disabled"
            return Result(stdout=f"{value}\n")
        if args == ["nmcli", "-g", "WIFI", "radio"]:
            if self.nm_radio_query_fail:
                return Result(returncode=1)
            value = "enabled" if self.nm_radio_software else "disabled"
            return Result(stdout=f"{value}\n")
        if args[:3] == ["nmcli", "device", "set"] and "autoconnect" in args:
            iface = args[3]
            value = args[args.index("autoconnect") + 1]
            self.nm_device_autoconnect[iface] = value == "yes"
            return Result()
        if args[:2] == ["nmcli", "-w"] and args[3:5] == ["device", "disconnect"]:
            self.nm_active.pop(args[5], None)
            return Result()
        if args[:4] == ["nmcli", "device", "wifi", "rescan"]:
            return Result()
        if (
            args[0] == "nmcli"
            and args[1:2] in (["-w"], ["--wait"])
            and args[3:6] == ["connection", "up", "uuid"]
        ):
            return self._connection_up(args[6])
        if args[:6] == ["nmcli", "-g", "SSID", "device", "wifi", "list"] and args[
            -2:
        ] == [
            "--rescan",
            "no",
        ]:
            iface = args[args.index("ifname") + 1]
            ssids = self.nm_wifi_cache.get(iface, set())
            return Result(stdout="\n".join(sorted(ssids)) + ("\n" if ssids else ""))
        return None

    def _device_show(self, fields: list[str], iface: str) -> Result:
        values = {
            "GENERAL.PATH": self.nm_path.get(iface, ""),
            "GENERAL.STATE": self.nm_device_state.get(iface, ""),
            "GENERAL.REASON": self.nm_device_reason.get(iface, ""),
            "GENERAL.CON-UUID": self.nm_active.get(iface, ""),
            "GENERAL.NM-MANAGED": "yes" if self.nm_managed.get(iface, True) else "no",
            "GENERAL.AUTOCONNECT": (
                "yes" if self.nm_device_autoconnect.get(iface, True) else "no"
            ),
        }
        return Result(
            stdout="\n".join(values.get(field, "") for field in fields) + "\n"
        )

    def _connection_up(self, uuid: str) -> Result:
        if uuid in self.nm_up_failures:
            return Result(returncode=4, stderr="Error: Connection activation failed.")
        if self.nm_auth_failure:
            return Result(
                returncode=4,
                stderr=(
                    "Error: Connection activation failed: Secrets were required, "
                    "but not provided"
                ),
            )
        profile = self.nm_profiles.get(uuid, {})
        interface = profile.get("connection.interface-name") or profile.get(
            "__bind_iface", ""
        )
        if interface and self.nm_auto_activate:
            self.nm_active[interface] = uuid
            address = profile.get("ipv4.addresses")
            gateway = profile.get("ipv4.gateway")
            table = profile.get("ipv4.route-table")
            if address:
                local, _, prefix = address.partition("/")
                self.routes.set_address(interface, local, int(prefix))
            if address and gateway and table:
                self.nm_routes[int(table)] = [
                    {
                        "dst": "default",
                        "dev": interface,
                        "gateway": gateway,
                        "prefsrc": local,
                    },
                    {
                        "dst": str(ip_interface(address).network),
                        "dev": interface,
                        "prefsrc": local,
                    },
                ]
            elif not address and interface in self.nm_dhcp:
                self._install_dhcp(uuid, interface, self.nm_dhcp[interface])
        return Result()

    def _autoactivate(self, uuid: str) -> None:
        """Model NetworkManager auto-activating an autoconnectable add."""
        if not self.nm_auto_activate:
            return
        profile = self.nm_profiles[uuid]
        interface = profile.get("__bind_iface", "")
        offer = self.nm_dhcp.get(interface) if interface else None
        if offer is not None:
            self._install_dhcp(uuid, interface, offer)

    def _install_dhcp(
        self,
        uuid: str,
        interface: str,
        offer: dict[str, object],
    ) -> None:
        """Assign a DHCP lease and install its routes into the profile's table.

        An unset ipv4.route-table lands the mobile default in the main table,
        exactly as NetworkManager does before route isolation is applied.
        """
        profile = self.nm_profiles[uuid]
        address = str(offer["address"])
        prefix = int(str(offer["prefix"]))
        gateway = str(offer["gateway"])
        self.nm_active[interface] = uuid
        self.routes.set_address(interface, address, prefix)
        network = str(ip_interface(f"{address}/{prefix}").network)
        default_route: dict[str, object] = {
            "dst": "default",
            "dev": interface,
            "gateway": gateway,
            "prefsrc": address,
        }
        network_route: dict[str, object] = {
            "dst": network,
            "dev": interface,
            "prefsrc": address,
        }
        table = profile.get("ipv4.route-table", "")
        if table and str(table).isdigit():
            self.nm_routes[int(table)] = [default_route, network_route]
            table_id: int | None = int(table)
        else:
            self.routes.add_main_default_route(default_route)
            table_id = None
        self.nm_dhcp_leases[uuid] = {
            "interface": interface,
            "address": (address, prefix),
            "table": table_id,
        }

    def _teardown_lease(self, uuid: str) -> None:
        """Tear down a DHCP lease and its routes as NetworkManager does."""
        lease = self.nm_dhcp_leases.pop(uuid, None)
        if lease is None:
            return
        interface = str(lease["interface"])
        address = cast(Address, lease["address"])
        self.routes.clear_address_if_matches(interface, address)
        table_id = lease["table"]
        if table_id is None:
            self.routes.remove_main_default_route_for(interface)
        else:
            self.nm_routes.pop(int(str(table_id)), None)
