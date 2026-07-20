from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

from rootfs.app.config import GatewayConfig
from rootfs.app.const import WIFI_HOTSPOT


class Result:
    def __init__(
        self,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeProcess:
    def __init__(
        self,
        *,
        running: bool = True,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.running = running
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def poll(self) -> int | None:
        return None if self.running else self.returncode

    def terminate(self) -> None:
        self.running = False

    def kill(self) -> None:
        self.running = False

    def wait(self, timeout: int = 5) -> int:
        if self.running:
            raise subprocess.TimeoutExpired("fake-process", timeout)
        return self.returncode

    def communicate(self, timeout: int = 1) -> tuple[str, str]:
        self.running = False
        return self.stdout, self.stderr


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.policy_rules: list[dict[str, object]] = []
        self.policy_routes: list[dict[str, object]] = []
        self.fail_ip_forward = False
        self.chain_listings: dict[tuple[str, str], str] = {}
        self.rule_checks: set[tuple[str, tuple[str, ...], tuple[str, ...]]] = set()
        self.idevice_udids: list[str] = []
        self.idevice_paired_udids: list[str] = []
        self.idevice_pair_result = Result(
            returncode=1, stdout="ERROR: Please accept the trust dialog\n"
        )
        self.idevice_validate_result = Result(
            returncode=1, stdout="ERROR: Device is not paired\n"
        )
        self.main_default_routes: list[dict[str, object]] = [
            {"dst": "default", "gateway": "192.168.1.1", "dev": "end0"}
        ]
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
        self.interface_addresses = {
            "end0": ("192.168.1.2", 24),
            "wlan0": ("172.20.10.4", 28),
        }
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

    def run(
        self,
        args: list[str],
        *,
        check: bool = True,
        timeout: int = 20,
    ) -> Result:
        self.commands.append(args)
        device_result = self._nm_device_command(args)
        if device_result is not None:
            return device_result
        if args == [
            "nmcli",
            "--escape",
            "no",
            "-g",
            "UUID",
            "connection",
            "show",
        ]:
            lines = list(self.nm_profiles)
            return Result(stdout="\n".join(lines) + ("\n" if lines else ""))
        if args[:4] == ["nmcli", "--escape", "no", "-g"] and args[5:7] == [
            "connection",
            "show",
        ]:
            fields = args[4].split(",")
            profile = self.nm_profiles.get(args[-1])
            if profile is None:
                return Result(returncode=10)
            return Result(
                stdout="\n".join(profile.get(field, "") for field in fields) + "\n"
            )
        if args[:3] == ["nmcli", "--show-secrets", "-g"]:
            fields = args[3].split(",")
            profile = self.nm_profiles.get(args[-1])
            if profile is None:
                return Result(returncode=10)
            return Result(
                stdout="\n".join(profile.get(field, "") for field in fields) + "\n"
            )
        if args[:2] == ["nmcli", "-g"] and args[3:5] == ["connection", "show"]:
            fields = args[2].split(",")
            profile = self.nm_profiles.get(args[-1])
            if profile is None:
                return Result(returncode=10)
            return Result(
                stdout="\n".join(profile.get(field, "") for field in fields) + "\n"
            )
        if args[:3] == ["nmcli", "connection", "add"]:
            pairs = args[3:]
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
            profile.update(
                {key: value for key, value in add_fields.items() if "." in key}
            )
            if "ssid" in add_fields:
                profile["802-11-wireless.ssid"] = add_fields["ssid"]
            ifname = add_fields.get("ifname", "")
            profile["__bind_iface"] = (
                ifname if ifname not in {"", "*"} else (self.nm_wildcard_bind or "")
            )
            self.nm_profiles[uuid] = profile
            if add_fields.get("connection.autoconnect", "yes") != "no":
                self._nm_autoactivate(uuid)
            return Result()
        if args[:3] == ["nmcli", "connection", "modify"]:
            profile = self.nm_profiles[args[3]]
            pairs = args[4:]
            for index in range(0, len(pairs), 2):
                profile[pairs[index]] = pairs[index + 1]
            return Result()
        if args[:4] == ["nmcli", "connection", "down", "uuid"]:
            uuid = args[4]
            for interface, active_uuid in list(self.nm_active.items()):
                if active_uuid == uuid:
                    del self.nm_active[interface]
            self._nm_teardown_lease(uuid)
            return Result()
        if args[:4] == ["nmcli", "connection", "delete", "uuid"]:
            if self.nm_delete_fail:
                return Result(returncode=1)
            uuid = args[4]
            for interface, active_uuid in list(self.nm_active.items()):
                if active_uuid == uuid:
                    del self.nm_active[interface]
            self._nm_teardown_lease(uuid)
            self.nm_profiles.pop(uuid, None)
            return Result()
        if args[:3] == ["nmcli", "-g", "GENERAL.CON-UUID"]:
            return Result(stdout=self.nm_active.get(args[-1], "") + "\n")
        if args[:3] == ["nmcli", "-g", "IP4.ADDRESS"]:
            configured = self.interface_addresses.get(args[-1])
            if configured is None:
                return Result(stdout="\n")
            addresses = configured if isinstance(configured, list) else [configured]
            return Result(
                stdout="\n".join(f"{address}/{prefix}" for address, prefix in addresses)
                + "\n"
            )
        if args[:2] == ["iptables", "--version"]:
            return Result(stdout="iptables v1.8.13 (nf_tables)\n")
        family = args[0] if args else ""
        action_index = 1
        if len(args) >= 3 and args[1] == "-t":
            action_index = 3
        if len(args) > action_index + 1 and args[action_index] == "-S":
            chain = args[action_index + 1]
            listing = self.chain_listings.get((family, chain))
            if listing is not None:
                return Result(stdout=listing)
        if (
            len(args) > action_index + 1
            and args[action_index] == "-S"
            and (family, args[action_index + 1])
            in {
                ("iptables", "DOCKER-USER"),
                ("iptables", "INPUT"),
                ("ip6tables", "DOCKER-USER"),
                ("ip6tables", "INPUT"),
            }
        ):
            return Result()
        if (
            len(args) > action_index + 1
            and args[action_index] == "-S"
            and args[action_index + 1].startswith("HA_CELL")
        ):
            return Result(returncode=1)
        if args[:4] == ["ip", "-4", "-j", "address"]:
            interface = args[-1]
            if interface not in self.interface_addresses:
                return Result(stdout="[]")
            configured = self.interface_addresses[interface]
            addresses = configured if isinstance(configured, list) else [configured]
            return Result(
                stdout=json.dumps(
                    [
                        {
                            "addr_info": [
                                {
                                    "family": "inet",
                                    "local": address,
                                    "prefixlen": prefix,
                                }
                                for address, prefix in addresses
                            ]
                        }
                    ]
                )
            )
        if args[:4] == ["ip", "-6", "-j", "address"]:
            return Result(stdout="[]")
        if args[:7] == [
            "ip",
            "-4",
            "-j",
            "route",
            "show",
            "table",
            "main",
        ]:
            return Result(stdout=json.dumps(self.main_default_routes))
        if args[:7] == [
            "ip",
            "-4",
            "-j",
            "route",
            "show",
            "table",
            "201",
        ]:
            return Result(stdout=json.dumps(self.policy_routes))
        if (
            args[:6] == ["ip", "-4", "-j", "route", "show", "table"]
            and args[6].isdigit()
        ):
            return Result(stdout=json.dumps(self.nm_routes.get(int(args[6]), [])))
        if args[:4] == ["ip", "-j", "rule", "show"]:
            return Result(stdout=json.dumps(self.policy_rules))
        if args[:4] in (
            ["ip", "-4", "address", "add"],
            ["ip", "-4", "address", "del"],
        ):
            address, interface = args[4], args[6]
            local, _, prefix = address.partition("/")
            value = (local, int(prefix))
            configured = self.interface_addresses.get(interface)
            addresses = (
                list(configured)
                if isinstance(configured, list)
                else ([configured] if configured else [])
            )
            if args[3] == "add":
                if value not in addresses:
                    addresses.append(value)
                self.interface_addresses[interface] = (
                    addresses[0] if len(addresses) == 1 else addresses
                )
                return Result()
            if value not in addresses:
                return Result(returncode=1)
            addresses.remove(value)
            if not addresses:
                self.interface_addresses.pop(interface, None)
            else:
                self.interface_addresses[interface] = (
                    addresses[0] if len(addresses) == 1 else addresses
                )
            return Result()
        if args[:3] in (["ip", "rule", "del"], ["ip", "route", "del"]):
            if args[:5] == ["ip", "route", "del", "default", "dev"]:
                interface = args[5]
                removed = False
                remaining = []
                for route in self.main_default_routes:
                    if (
                        route.get("dev") == interface
                        and route.get("dst") == "default"
                        and not removed
                    ):
                        removed = True
                        continue
                    remaining.append(route)
                self.main_default_routes = remaining
                return Result(returncode=0 if removed else 1)
            return Result(returncode=1)
        if args[:2] == ["idevice_id", "--list"]:
            return Result(
                stdout="\n".join(self.idevice_udids)
                + ("\n" if self.idevice_udids else "")
            )
        if args[:2] == ["idevicepair", "list"]:
            return Result(
                stdout="\n".join(self.idevice_paired_udids)
                + ("\n" if self.idevice_paired_udids else "")
            )
        if args and args[0] == "idevicepair" and "--udid" in args:
            if args[-1] == "validate":
                return self.idevice_validate_result
            if args[-1] == "pair":
                return self.idevice_pair_result
        if "-C" in args:
            index = args.index("-C")
            if (
                args[0],
                tuple(args[1:index]),
                tuple(args[index + 1 :]),
            ) in self.rule_checks:
                return Result()
            return Result(returncode=1)
        if family in {"iptables", "ip6tables"} and len(args) > action_index:
            action = args[action_index]
            command = args[action_index + 1 :]
            if action == "-N" and command:
                self.chain_listings.setdefault((family, command[0]), f"-N {command[0]}")
            elif action == "-F" and command:
                self._flush_chain(family, command[0])
            elif action == "-X" and command:
                self.chain_listings.pop((family, command[0]), None)
            elif action == "-A" and len(command) >= 2:
                self._append_rule(family, command[0], command[1:])
            elif action == "-I" and len(command) >= 3:
                self._insert_rule(
                    family,
                    command[0],
                    int(command[1]),
                    command[2:],
                )
            elif action == "-D" and len(command) >= 1:
                self._delete_rule(family, command[0], command[1:])
        if args and args[0] == "curl":
            return Result(stdout="ip=203.0.113.10\n")
        return Result()

    def _nm_device_command(self, args: list[str]) -> "Result | None":
        if (
            args[:2] == ["nmcli", "-g"]
            and args[3:5] == ["device", "show"]
            and all(field.startswith("GENERAL.") for field in args[2].split(","))
        ):
            return self._nm_device_show(args[2].split(","), args[-1])
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
            return self._nm_connection_up(args[6])
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

    def _nm_device_show(self, fields: list[str], iface: str) -> Result:
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

    def _nm_connection_up(self, uuid: str) -> Result:
        if uuid in self.nm_up_failures:
            return Result(
                returncode=4,
                stderr="Error: Connection activation failed.",
            )
        if self.nm_auth_failure:
            return Result(
                returncode=4,
                stderr="Error: Connection activation failed: Secrets were required, but not provided",
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
                self.interface_addresses[interface] = (local, int(prefix))
            if address and gateway and table:
                from ipaddress import ip_interface

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
                self._nm_install_dhcp(uuid, interface, self.nm_dhcp[interface])
        return Result()

    def _nm_autoactivate(self, uuid: str) -> None:
        """Model NetworkManager auto-activating an autoconnectable add."""
        if not self.nm_auto_activate:
            return
        profile = self.nm_profiles[uuid]
        interface = profile.get("__bind_iface", "")
        offer = self.nm_dhcp.get(interface) if interface else None
        if offer is not None:
            self._nm_install_dhcp(uuid, interface, offer)

    def _nm_install_dhcp(
        self,
        uuid: str,
        interface: str,
        offer: dict[str, object],
    ) -> None:
        """Assign a DHCP lease and install its routes into the profile's table.

        An unset ipv4.route-table lands the mobile default in the main table,
        exactly as NetworkManager does before route isolation is applied.
        """
        from ipaddress import ip_interface

        profile = self.nm_profiles[uuid]
        address = str(offer["address"])
        prefix = int(str(offer["prefix"]))
        gateway = str(offer["gateway"])
        self.nm_active[interface] = uuid
        self.interface_addresses[interface] = (address, prefix)
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
            self.main_default_routes = [*self.main_default_routes, default_route]
            table_id = None
        self.nm_dhcp_leases[uuid] = {
            "interface": interface,
            "address": (address, prefix),
            "table": table_id,
        }

    def _nm_teardown_lease(self, uuid: str) -> None:
        """Tear down a DHCP lease and its routes as NetworkManager does."""
        lease = self.nm_dhcp_leases.pop(uuid, None)
        if lease is None:
            return
        interface = str(lease["interface"])
        if self.interface_addresses.get(interface) == lease["address"]:
            self.interface_addresses.pop(interface, None)
        table_id = lease["table"]
        if table_id is None:
            self.main_default_routes = [
                route
                for route in self.main_default_routes
                if not (route.get("dev") == interface and route.get("dst") == "default")
            ]
        else:
            self.nm_routes.pop(int(str(table_id)), None)

    def _chain_lines(self, family: str, chain: str) -> list[str]:
        listing = self.chain_listings.get((family, chain))
        return [] if not listing else listing.splitlines()

    def _set_chain_lines(self, family: str, chain: str, lines: list[str]) -> None:
        self.chain_listings[(family, chain)] = "\n".join(lines)

    def _append_rule(self, family: str, chain: str, rule: list[str]) -> None:
        lines = self._chain_lines(family, chain)
        lines.append(self._rule_line(chain, rule))
        self._set_chain_lines(family, chain, lines)

    def _insert_rule(
        self,
        family: str,
        chain: str,
        position: int,
        rule: list[str],
    ) -> None:
        lines = self._chain_lines(family, chain)
        header = 1 if lines[:1] == [f"-N {chain}"] else 0
        insert_at = min(header + max(position - 1, 0), len(lines))
        lines.insert(insert_at, self._rule_line(chain, rule))
        self._set_chain_lines(family, chain, lines)

    def _delete_rule(self, family: str, chain: str, spec: list[str]) -> None:
        lines = self._chain_lines(family, chain)
        rule_indexes = [
            index for index, line in enumerate(lines) if line.startswith(f"-A {chain} ")
        ]
        if not rule_indexes:
            return
        if len(spec) == 1 and spec[0].isdigit():
            position = int(spec[0])
            if 1 <= position <= len(rule_indexes):
                del lines[rule_indexes[position - 1]]
                self._set_chain_lines(family, chain, lines)
            return
        target = self._rule_line(chain, spec)
        for index in rule_indexes:
            if lines[index] == target:
                del lines[index]
                self._set_chain_lines(family, chain, lines)
                return

    def _flush_chain(self, family: str, chain: str) -> None:
        lines = self._chain_lines(family, chain)
        if lines[:1] == [f"-N {chain}"]:
            self._set_chain_lines(family, chain, [lines[0]])
            return
        self._set_chain_lines(family, chain, [])

    @staticmethod
    def _rule_line(chain: str, rule: list[str]) -> str:
        return shlex.join(["-A", chain, *rule])


class FakeWifiProfileMetadata:
    """In-memory stand-in for the app Wi-Fi profile's NetworkManager metadata."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def read(self, key: str) -> str | None:
        return self.data.get(key)

    def write(self, key: str, value: str) -> None:
        self.data[key] = value

    def clear(self, key: str) -> None:
        self.data.pop(key, None)


def build_engine(config: GatewayConfig, **kwargs: object):
    """Construct a GatewayEngine with an in-memory Wi-Fi metadata store."""
    from rootfs.app.gateway import GatewayEngine

    kwargs.setdefault("wifi_metadata", FakeWifiProfileMetadata())
    return GatewayEngine(config, **kwargs)  # type: ignore[arg-type]


def make_config(**overrides: object) -> GatewayConfig:
    values = {
        "auto_disable_minutes": 30,
        "mobile_connection": WIFI_HOTSPOT,
        "upstream_interface": "wlan0",
        "upstream_address": "172.20.10.4/28",
        "upstream_gateway": "172.20.10.1",
        "hotspot_ssid": "",
        "hotspot_password": "",
        "downstream_mac": "00:11:22:33:44:55",
        "downstream_address": "192.168.80.1/24",
    }
    values.update(overrides)
    return GatewayConfig(**values)


def install_realistic_firewall_state(
    runner: FakeRunner,
    firewall,
    downstream: str,
    upstream: str | None = None,
) -> None:
    upstream = upstream or firewall.config.upstream_interface
    subnet = firewall.config.transit_subnet
    runner.rule_checks.update(
        {
            (
                "iptables",
                tuple(),
                (
                    "INPUT",
                    *firewall.netfilter.jump_rule(
                        firewall.INPUT_CHAIN,
                        "ha-cellgw:local-jump",
                        ["-i", downstream],
                    ),
                ),
            ),
            (
                "iptables",
                tuple(),
                (
                    "DOCKER-USER",
                    *firewall.netfilter.jump_rule(
                        firewall.FORWARD_CHAIN,
                        "ha-cellgw:jump",
                    ),
                ),
            ),
            (
                "iptables",
                ("-t", "nat"),
                ("POSTROUTING", *firewall._nat_rule(upstream)),
            ),
            *{
                (
                    "iptables",
                    ("-t", "mangle"),
                    ("FORWARD", *rule),
                )
                for rule in firewall._mss_rules(downstream, upstream)
            },
            (
                "ip6tables",
                tuple(),
                (
                    "INPUT",
                    *firewall.netfilter.jump_rule(
                        firewall.INPUT6_CHAIN,
                        "ha-cellgw:v6-local-jump",
                        ["-i", downstream],
                    ),
                ),
            ),
            (
                "ip6tables",
                tuple(),
                (
                    "DOCKER-USER",
                    *firewall.netfilter.jump_rule(
                        firewall.FORWARD6_CHAIN,
                        "ha-cellgw:v6-jump",
                    ),
                ),
            ),
        }
    )
    runner.chain_listings.update(
        {
            (
                "iptables",
                "INPUT",
            ): "\n".join(
                (
                    f"-A INPUT -i {downstream} -m comment --comment ha-cellgw:local-jump -j {firewall.INPUT_CHAIN}",
                )
            ),
            (
                "iptables",
                "DOCKER-USER",
            ): "\n".join(
                (
                    f"-A DOCKER-USER -m comment --comment ha-cellgw:jump -j {firewall.FORWARD_CHAIN}",
                )
            ),
            (
                "iptables",
                firewall.INPUT_CHAIN,
            ): "\n".join(
                (
                    f"-N {firewall.INPUT_CHAIN}",
                    "-A HA_CELLGW_LOCAL -m conntrack --ctstate RELATED,ESTABLISHED "
                    "-m comment --comment ha-cellgw:local-established -j ACCEPT",
                    "-A HA_CELLGW_LOCAL -p udp -m udp --sport 68 --dport 67 "
                    "-m comment --comment ha-cellgw:dhcp-in -j ACCEPT",
                    "-A HA_CELLGW_LOCAL -p icmp -m comment --comment ha-cellgw:icmp-in -j ACCEPT",
                    "-A HA_CELLGW_LOCAL -m comment --comment ha-cellgw:local-drop -j DROP",
                )
            ),
            (
                "iptables",
                firewall.FORWARD_CHAIN,
            ): "\n".join(
                (
                    f"-N {firewall.FORWARD_CHAIN}",
                    f"-A HA_CELLGW -i {downstream} -o {upstream} -s {subnet} "
                    "-m conntrack --ctstate ESTABLISHED,NEW -m comment "
                    "--comment ha-cellgw:out -j ACCEPT",
                    f"-A HA_CELLGW -i {upstream} -o {downstream} -d {subnet} "
                    "-m conntrack --ctstate RELATED,ESTABLISHED -m comment "
                    "--comment ha-cellgw:in -j ACCEPT",
                    f"-A HA_CELLGW -i {downstream} ! -o {upstream} -m comment --comment ha-cellgw:drop-out -j DROP",
                    f"-A HA_CELLGW ! -i {upstream} -o {downstream} -m comment --comment ha-cellgw:drop-in -j DROP",
                    "-A HA_CELLGW -j RETURN",
                )
            ),
            (
                "ip6tables",
                "INPUT",
            ): "\n".join(
                (
                    f"-A INPUT -i {downstream} -m comment --comment ha-cellgw:v6-local-jump -j {firewall.INPUT6_CHAIN}",
                )
            ),
            (
                "ip6tables",
                "DOCKER-USER",
            ): "\n".join(
                (
                    f"-A DOCKER-USER -m comment --comment ha-cellgw:v6-jump -j {firewall.FORWARD6_CHAIN}",
                )
            ),
            (
                "ip6tables",
                firewall.INPUT6_CHAIN,
            ): "\n".join(
                (
                    f"-N {firewall.INPUT6_CHAIN}",
                    "-A HA_CELLGW6_LOCAL -j DROP",
                )
            ),
            (
                "ip6tables",
                firewall.FORWARD6_CHAIN,
            ): "\n".join(
                (
                    f"-N {firewall.FORWARD6_CHAIN}",
                    f"-A HA_CELLGW6 -i {downstream} -j DROP",
                    f"-A HA_CELLGW6 -o {downstream} -j DROP",
                    "-A HA_CELLGW6 -j RETURN",
                )
            ),
        }
    )


def install_realistic_policy_state(
    runner: FakeRunner,
    policy,
    downstream: str,
    upstream=None,
) -> None:
    ownership = policy.ownership(downstream, upstream)
    runner.policy_rules = []
    for rule in policy.rule_args(ownership):
        entry = {
            "priority": int(rule[rule.index("pref") + 1]),
            "table": rule[rule.index("lookup") + 1],
        }
        if "iif" in rule:
            entry["iifname"] = rule[rule.index("iif") + 1]
        if "from" in rule:
            source = rule[rule.index("from") + 1]
            if "/" in source:
                address, _, length = source.partition("/")
                entry["src"] = address
                entry["srclen"] = int(length)
            else:
                entry["src"] = source
        runner.policy_rules.append(entry)
    runner.policy_routes = [
        {
            "dst": route[0],
            "dev": route[route.index("dev") + 1],
            "prefsrc": route[route.index("src") + 1],
            **({"gateway": route[route.index("via") + 1]} if "via" in route else {}),
        }
        for route in policy.route_args(ownership)
    ]


def prepend_chain_rule(
    runner: FakeRunner,
    family: str,
    chain: str,
    rule: str,
) -> None:
    listing = runner.chain_listings.get((family, chain), "")
    runner.chain_listings[(family, chain)] = f"{rule}\n{listing}" if listing else rule


def sysctl_values() -> dict[Path, str]:
    return {
        Path("/proc/sys/net/ipv4/ip_forward"): "1",
        Path("/proc/sys/net/ipv4/conf/all/rp_filter"): "0",
        Path("/proc/sys/net/ipv4/conf/default/rp_filter"): "2",
        Path("/proc/sys/net/ipv4/conf/end0/rp_filter"): "2",
        Path("/proc/sys/net/ipv4/conf/wlan0/rp_filter"): "2",
        Path("/proc/sys/net/ipv4/conf/eth0/rp_filter"): "2",
        Path("/proc/sys/net/ipv4/conf/enx001122334455/rp_filter"): "2",
    }
