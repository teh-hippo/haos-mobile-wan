from __future__ import annotations

import json
from typing import Union

from .process import Result

Address = tuple[str, int]
AddressBook = Union[Address, list[Address]]


class RouteInterfaceState:
    def __init__(self) -> None:
        self.interface_addresses: dict[str, AddressBook] = {
            "end0": ("192.168.1.2", 24),
            "wlan0": ("172.20.10.4", 28),
        }
        self.main_default_routes: list[dict[str, object]] = [
            {"dst": "default", "gateway": "192.168.1.1", "dev": "end0"}
        ]
        self.policy_rules: list[dict[str, object]] = []
        self.policy_routes: list[dict[str, object]] = []

    def dispatch(
        self,
        args: list[str],
        *,
        nm_routes: dict[int, list[dict[str, object]]],
    ) -> Result | None:
        if args[:4] == ["ip", "-4", "-j", "address"]:
            return self._show_address(args[-1])
        if args[:4] == ["ip", "-6", "-j", "address"]:
            return Result(stdout="[]")
        if args[:7] == ["ip", "-4", "-j", "route", "show", "table", "main"]:
            return Result(stdout=json.dumps(self.main_default_routes))
        if args[:7] == ["ip", "-4", "-j", "route", "show", "table", "201"]:
            return Result(stdout=json.dumps(self.policy_routes))
        if (
            args[:6] == ["ip", "-4", "-j", "route", "show", "table"]
            and args[6].isdigit()
        ):
            return Result(stdout=json.dumps(nm_routes.get(int(args[6]), [])))
        if args[:4] == ["ip", "-j", "rule", "show"]:
            return Result(stdout=json.dumps(self.policy_rules))
        if args[:4] in (
            ["ip", "-4", "address", "add"],
            ["ip", "-4", "address", "del"],
        ):
            return self._address_add_del(args)
        if args[:3] in (["ip", "rule", "del"], ["ip", "route", "del"]):
            return self._route_del(args)
        return None

    def get_address(self, interface: str) -> AddressBook | None:
        return self.interface_addresses.get(interface)

    def set_address(self, interface: str, address: str, prefix: int) -> None:
        self.interface_addresses[interface] = (address, prefix)

    def clear_address_if_matches(self, interface: str, value: AddressBook) -> None:
        if self.interface_addresses.get(interface) == value:
            self.interface_addresses.pop(interface, None)

    def add_main_default_route(self, route: dict[str, object]) -> None:
        self.main_default_routes = [*self.main_default_routes, route]

    def remove_main_default_route_for(self, interface: str) -> None:
        self.main_default_routes = [
            route
            for route in self.main_default_routes
            if not (route.get("dev") == interface and route.get("dst") == "default")
        ]

    def _show_address(self, interface: str) -> Result:
        configured = self.interface_addresses.get(interface)
        if configured is None:
            return Result(stdout="[]")
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

    def _address_add_del(self, args: list[str]) -> Result:
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

    def _route_del(self, args: list[str]) -> Result:
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
