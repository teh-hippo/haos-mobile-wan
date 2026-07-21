from __future__ import annotations

from .process import Result
from .runner_firewall import FirewallCommandState
from .runner_networkmanager import NetworkManagerState
from .runner_routes import RouteInterfaceState
from .runner_usb import UsbCommandState


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.routes = RouteInterfaceState()
        self.networkmanager = NetworkManagerState(self.routes)
        self.firewall = FirewallCommandState()
        self.usb = UsbCommandState()

    def run(
        self,
        args: list[str],
        *,
        check: bool = True,
        timeout: int = 20,
    ) -> Result:
        self.commands.append(args)
        nm_result = self.networkmanager.dispatch(args)
        if nm_result is not None:
            return nm_result
        firewall_result = self.firewall.dispatch(args)
        if firewall_result is not None:
            return firewall_result
        route_result = self.routes.dispatch(
            args, nm_routes=self.networkmanager.nm_routes
        )
        if route_result is not None:
            return route_result
        usb_result = self.usb.dispatch(args)
        if usb_result is not None:
            return usb_result
        if args and args[0] == "curl":
            return Result(stdout="ip=203.0.113.10\n")
        return Result()
