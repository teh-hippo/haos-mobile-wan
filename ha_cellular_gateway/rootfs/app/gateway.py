from __future__ import annotations

import ipaddress
import json
import os
import secrets
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


OPTIONS_PATH = Path(os.environ.get("CELLGW_OPTIONS", "/data/options.json"))
TOKEN_PATH = Path(os.environ.get("CELLGW_TOKEN", "/data/api_token"))
RUN_DIR = Path(os.environ.get("CELLGW_RUN_DIR", "/run/ha-cellgw"))
LEASE_PATH = Path(os.environ.get("CELLGW_LEASES", "/data/dnsmasq.leases"))


class GatewayError(RuntimeError):
    pass


class SafetyError(GatewayError):
    pass


@dataclass(frozen=True)
class GatewayConfig:
    mode: str
    dry_run: bool
    management_interface: str
    management_address: str
    upstream_interface: str
    upstream_ssid: str
    upstream_address: str
    upstream_gateway: str
    downstream_mac: str
    downstream_address: str
    transit_subnet: str
    dhcp_start: str
    dhcp_end: str
    dns_servers: tuple[str, ...]
    routing_table: int
    reconcile_seconds: int
    trial_seconds: int
    api_bind: str
    api_port: int

    @classmethod
    def from_path(cls, path: Path = OPTIONS_PATH) -> "GatewayConfig":
        data = json.loads(path.read_text(encoding="utf-8"))
        config = cls(
            mode=str(data.get("mode", "disabled")),
            dry_run=bool(data.get("dry_run", True)),
            management_interface=str(data.get("management_interface", "end0")),
            management_address=str(data.get("management_address", "192.168.1.2/24")),
            upstream_interface=str(data.get("upstream_interface", "wlan0")),
            upstream_ssid=str(data.get("upstream_ssid", "MobileHotspot")),
            upstream_address=str(data.get("upstream_address", "172.20.10.4/28")),
            upstream_gateway=str(data.get("upstream_gateway", "172.20.10.1")),
            downstream_mac=str(data.get("downstream_mac", "")).lower(),
            downstream_address=str(data.get("downstream_address", "192.168.80.1/24")),
            transit_subnet=str(data.get("transit_subnet", "192.168.80.0/24")),
            dhcp_start=str(data.get("dhcp_start", "192.168.80.10")),
            dhcp_end=str(data.get("dhcp_end", "192.168.80.50")),
            dns_servers=tuple(data.get("dns_servers", ["1.1.1.1", "8.8.8.8"])),
            routing_table=int(data.get("routing_table", 201)),
            reconcile_seconds=max(2, int(data.get("reconcile_seconds", 5))),
            trial_seconds=max(60, int(data.get("trial_seconds", 300))),
            api_bind=str(data.get("api_bind", "172.30.32.1")),
            api_port=int(data.get("api_port", 8099)),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.mode not in {"disabled", "trial", "active"}:
            raise GatewayError(f"Unsupported mode: {self.mode}")

        management = ipaddress.ip_interface(self.management_address)
        upstream = ipaddress.ip_interface(self.upstream_address)
        downstream = ipaddress.ip_interface(self.downstream_address)
        transit = ipaddress.ip_network(self.transit_subnet)
        gateway = ipaddress.ip_address(self.upstream_gateway)
        dhcp_start = ipaddress.ip_address(self.dhcp_start)
        dhcp_end = ipaddress.ip_address(self.dhcp_end)

        if management.version != 4 or upstream.version != 4 or downstream.version != 4:
            raise GatewayError("Only IPv4 gateway mode is supported")
        if gateway not in upstream.network:
            raise GatewayError("Upstream gateway is outside the upstream subnet")
        if downstream.ip not in transit:
            raise GatewayError("Downstream address is outside the transit subnet")
        if dhcp_start not in transit or dhcp_end not in transit or dhcp_start > dhcp_end:
            raise GatewayError("Invalid DHCP range")
        if management.network == transit or upstream.network == transit:
            raise GatewayError("Management, upstream and transit networks must differ")
        if self.routing_table < 1 or self.routing_table > 4_294_967_295:
            raise GatewayError("Invalid routing table")
        for dns in self.dns_servers:
            if ipaddress.ip_address(dns).version != 4:
                raise GatewayError("Only IPv4 DNS servers are supported")

    @property
    def upstream_ip(self) -> str:
        return str(ipaddress.ip_interface(self.upstream_address).ip)

    @property
    def upstream_network(self) -> str:
        return str(ipaddress.ip_interface(self.upstream_address).network)

    @property
    def downstream_ip(self) -> str:
        return str(ipaddress.ip_interface(self.downstream_address).ip)


class CommandRunner:
    def run(
        self,
        args: list[str],
        *,
        check: bool = True,
        timeout: int = 20,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            check=check,
            capture_output=True,
            text=True,
            timeout=timeout,
        )


class GatewayEngine:
    FILTER_CHAIN = "HA_CELLGW"
    FILTER6_CHAIN = "HA_CELLGW6"
    COMMENT_PREFIX = "ha-cellgw"
    RULE_PRIORITIES = (20100, 20110, 20120)

    def __init__(
        self,
        config: GatewayConfig,
        *,
        runner: CommandRunner | None = None,
        read_text: Callable[[Path], str] | None = None,
    ) -> None:
        self.config = config
        self.runner = runner or CommandRunner()
        self.read_text = read_text or (lambda path: path.read_text(encoding="utf-8"))
        self.lock = threading.RLock()
        self.mode = "disabled"
        self.desired_mode = config.mode if config.mode in {"trial", "active"} else "disabled"
        self.last_error: str | None = None
        self.last_reconcile: float | None = None
        self.trial_deadline: float | None = None
        self.dnsmasq: subprocess.Popen[str] | None = None
        self.stop_event = threading.Event()
        self.applied = False

    def _run(
        self,
        *args: str,
        check: bool = True,
        timeout: int = 20,
    ) -> subprocess.CompletedProcess[str]:
        return self.runner.run(list(args), check=check, timeout=timeout)

    def _read_json(self, *args: str) -> object:
        result = self._run(*args)
        return json.loads(result.stdout or "[]")

    def _interface_addresses(self, interface: str, family: int = 4) -> set[str]:
        data = self._read_json("ip", f"-{family}", "-j", "address", "show", "dev", interface)
        addresses: set[str] = set()
        for item in data if isinstance(data, list) else []:
            for addr in item.get("addr_info", []):
                if addr.get("family") == ("inet" if family == 4 else "inet6"):
                    addresses.add(f"{addr['local']}/{addr['prefixlen']}")
        return addresses

    def _find_interface_by_mac(self) -> str | None:
        if not self.config.downstream_mac:
            return None
        root = Path("/sys/class/net")
        if not root.exists():
            return None
        for interface in root.iterdir():
            address_path = interface / "address"
            try:
                if self.read_text(address_path).strip().lower() == self.config.downstream_mac:
                    return interface.name
            except OSError:
                continue
        return None

    def _main_default_interfaces(self) -> set[str]:
        routes = self._read_json("ip", "-4", "-j", "route", "show", "table", "main", "default")
        return {route["dev"] for route in routes if "dev" in route}

    def _policy_rule_conflicts(self) -> list[str]:
        rules = self._read_json("ip", "-j", "rule", "show")
        conflicts: list[str] = []
        for rule in rules if isinstance(rules, list) else []:
            priority = int(rule.get("priority", -1))
            if priority not in self.RULE_PRIORITIES:
                continue
            table = str(rule.get("table", rule.get("lookup", "")))
            if table != str(self.config.routing_table):
                conflicts.append(f"Policy priority {priority} is already in use")
        return conflicts

    def _rp_filter(self, interface: str) -> int:
        path = Path(f"/proc/sys/net/ipv4/conf/{interface}/rp_filter")
        return int(self.read_text(path).strip())

    def _ip_forward(self) -> int:
        return int(self.read_text(Path("/proc/sys/net/ipv4/ip_forward")).strip())

    def _iptables_backend_ok(self) -> bool:
        result = self._run("iptables", "--version", check=False)
        return result.returncode == 0 and "nf_tables" in result.stdout

    def _chain_exists(self, family: str, chain: str) -> bool:
        result = self._run(family, "-S", chain, check=False)
        return result.returncode == 0

    def _rules_installed(self) -> bool:
        if not self._chain_exists("iptables", self.FILTER_CHAIN):
            return False
        return (
            self._run(
                "iptables",
                "-C",
                "DOCKER-USER",
                "-j",
                self.FILTER_CHAIN,
                check=False,
            ).returncode
            == 0
        )

    def safety_errors(self, downstream: str | None = None) -> list[str]:
        downstream = downstream or self._find_interface_by_mac()
        errors: list[str] = []

        try:
            management_addresses = self._interface_addresses(self.config.management_interface)
            if self.config.management_address not in management_addresses:
                errors.append("Management interface/address baseline does not match")
        except (GatewayError, OSError, subprocess.SubprocessError, ValueError):
            errors.append("Management interface is unavailable")

        if self._ip_forward() != 1:
            errors.append("Host IPv4 forwarding is not enabled")

        for interface in ("all", "default", self.config.management_interface, self.config.upstream_interface):
            try:
                if self._rp_filter(interface) == 1:
                    errors.append(f"Strict rp_filter is enabled on {interface}")
            except (OSError, ValueError):
                errors.append(f"Cannot read rp_filter for {interface}")

        if not self._iptables_backend_ok():
            errors.append("iptables is not using the nf_tables backend")
        if not self._chain_exists("iptables", "DOCKER-USER"):
            errors.append("Docker DOCKER-USER chain is missing")

        try:
            upstream_addresses = self._interface_addresses(self.config.upstream_interface)
            if self.config.upstream_address not in upstream_addresses:
                errors.append("Upstream interface/address is not active")
        except (GatewayError, OSError, subprocess.SubprocessError, ValueError):
            errors.append("Upstream interface is unavailable")

        default_interfaces = self._main_default_interfaces()
        if self.config.management_interface not in default_interfaces:
            errors.append("Management interface is not the main default route")
        unexpected_defaults = default_interfaces - {self.config.management_interface}
        if unexpected_defaults:
            errors.append(
                "Unexpected main-table default route: "
                + ",".join(sorted(unexpected_defaults))
            )
        if self.config.upstream_interface in default_interfaces:
            errors.append("Cellular upstream has a main-table default route")
        try:
            errors.extend(self._policy_rule_conflicts())
        except (GatewayError, subprocess.SubprocessError, ValueError):
            errors.append("Cannot inspect policy-routing priorities")

        if downstream is None:
            errors.append("Configured downstream NIC is not present")
        else:
            try:
                downstream_addresses = self._interface_addresses(downstream)
                if self.config.downstream_address not in downstream_addresses:
                    errors.append("Downstream interface/address is not active")
                if self._rp_filter(downstream) == 1:
                    errors.append("Strict rp_filter is enabled on downstream NIC")
            except (GatewayError, OSError, subprocess.SubprocessError, ValueError):
                errors.append("Downstream interface is unavailable")

            try:
                if self._interface_addresses(downstream, family=6):
                    errors.append("IPv6 is active on downstream NIC")
            except (GatewayError, OSError, subprocess.SubprocessError, ValueError):
                errors.append("Cannot verify downstream IPv6 state")

        try:
            if self._interface_addresses(self.config.upstream_interface, family=6):
                errors.append("IPv6 is active on cellular upstream")
        except (GatewayError, OSError, subprocess.SubprocessError, ValueError):
            errors.append("Cannot verify upstream IPv6 state")

        return errors

    def _delete_rule(self, table_args: list[str], rule: list[str]) -> None:
        while self._run("iptables", *table_args, "-C", *rule, check=False).returncode == 0:
            self._run("iptables", *table_args, "-D", *rule, check=False)

    def _ensure_rule(
        self,
        table_args: list[str],
        chain: str,
        rule: list[str],
        *,
        insert: bool = False,
    ) -> None:
        check_args = [*table_args, "-C", chain, *rule]
        if self._run("iptables", *check_args, check=False).returncode == 0:
            return
        operation = "-I" if insert else "-A"
        self._run("iptables", *table_args, operation, chain, *rule)

    def _ensure_jump(self, family: str, parent: str, child: str, comment: str) -> None:
        rule = ["-j", child, "-m", "comment", "--comment", comment]
        if self._run(family, "-C", parent, *rule, check=False).returncode != 0:
            self._run(family, "-I", parent, "1", *rule)

    def _ensure_chain(self, family: str, chain: str) -> None:
        if self._run(family, "-S", chain, check=False).returncode != 0:
            self._run(family, "-N", chain)
        self._run(family, "-F", chain)

    def _apply_policy_routing(self, downstream: str) -> None:
        table = str(self.config.routing_table)
        for priority in self.RULE_PRIORITIES:
            while self._run("ip", "rule", "del", "pref", str(priority), check=False).returncode == 0:
                pass
        self._run(
            "ip",
            "route",
            "replace",
            self.config.upstream_network,
            "dev",
            self.config.upstream_interface,
            "src",
            self.config.upstream_ip,
            "table",
            table,
        )
        self._run(
            "ip",
            "route",
            "replace",
            "default",
            "via",
            self.config.upstream_gateway,
            "dev",
            self.config.upstream_interface,
            "table",
            table,
        )
        self._run("ip", "rule", "add", "pref", "20100", "iif", downstream, "lookup", table)
        self._run(
            "ip",
            "rule",
            "add",
            "pref",
            "20110",
            "from",
            self.config.transit_subnet,
            "lookup",
            table,
        )
        self._run(
            "ip",
            "rule",
            "add",
            "pref",
            "20120",
            "from",
            f"{self.config.upstream_ip}/32",
            "lookup",
            table,
        )

    def _apply_firewall(self, downstream: str) -> None:
        up = self.config.upstream_interface
        subnet = self.config.transit_subnet
        tag = self.COMMENT_PREFIX

        self._ensure_chain("iptables", self.FILTER_CHAIN)
        self._ensure_jump("iptables", "DOCKER-USER", self.FILTER_CHAIN, f"{tag}:jump")
        self._run(
            "iptables",
            "-A",
            self.FILTER_CHAIN,
            "-i",
            downstream,
            "-o",
            up,
            "-s",
            subnet,
            "-m",
            "conntrack",
            "--ctstate",
            "NEW,ESTABLISHED",
            "-j",
            "ACCEPT",
            "-m",
            "comment",
            "--comment",
            f"{tag}:out",
        )
        self._run(
            "iptables",
            "-A",
            self.FILTER_CHAIN,
            "-i",
            up,
            "-o",
            downstream,
            "-d",
            subnet,
            "-m",
            "conntrack",
            "--ctstate",
            "ESTABLISHED,RELATED",
            "-j",
            "ACCEPT",
            "-m",
            "comment",
            "--comment",
            f"{tag}:in",
        )
        self._run(
            "iptables",
            "-A",
            self.FILTER_CHAIN,
            "-i",
            downstream,
            "!",
            "-o",
            up,
            "-j",
            "DROP",
            "-m",
            "comment",
            "--comment",
            f"{tag}:drop-out",
        )
        self._run(
            "iptables",
            "-A",
            self.FILTER_CHAIN,
            "!",
            "-i",
            up,
            "-o",
            downstream,
            "-j",
            "DROP",
            "-m",
            "comment",
            "--comment",
            f"{tag}:drop-in",
        )
        self._run("iptables", "-A", self.FILTER_CHAIN, "-j", "RETURN")

        nat_rule = [
            "POSTROUTING",
            "-s",
            subnet,
            "-o",
            up,
            "-j",
            "MASQUERADE",
            "-m",
            "comment",
            "--comment",
            f"{tag}:snat",
        ]
        self._ensure_rule(["-t", "nat"], nat_rule[0], nat_rule[1:])

        for direction, interface in (("-o", up), ("-i", up)):
            if direction == "-o":
                match = ["-i", downstream, "-o", up, "-s", subnet]
            else:
                match = ["-i", up, "-o", downstream, "-d", subnet]
            rule = [
                "FORWARD",
                *match,
                "-p",
                "tcp",
                "--tcp-flags",
                "SYN,RST",
                "SYN",
                "-j",
                "TCPMSS",
                "--clamp-mss-to-pmtu",
                "-m",
                "comment",
                "--comment",
                f"{tag}:mss-{direction[-1]}",
            ]
            self._ensure_rule(["-t", "mangle"], rule[0], rule[1:])

        if self._chain_exists("ip6tables", "DOCKER-USER"):
            self._ensure_chain("ip6tables", self.FILTER6_CHAIN)
            self._ensure_jump("ip6tables", "DOCKER-USER", self.FILTER6_CHAIN, f"{tag}:v6-jump")
            self._run("ip6tables", "-A", self.FILTER6_CHAIN, "-i", downstream, "-j", "DROP")
            self._run("ip6tables", "-A", self.FILTER6_CHAIN, "-o", downstream, "-j", "DROP")
            self._run("ip6tables", "-A", self.FILTER6_CHAIN, "-j", "RETURN")

    def _dnsmasq_config(self, downstream: str) -> str:
        dns = ",".join(self.config.dns_servers)
        return "\n".join(
            (
                f"interface={downstream}",
                "bind-dynamic",
                f"listen-address={self.config.downstream_ip}",
                "port=0",
                "dhcp-authoritative",
                (
                    f"dhcp-range={self.config.dhcp_start},{self.config.dhcp_end},"
                    f"{ipaddress.ip_network(self.config.transit_subnet).netmask},12h"
                ),
                f"dhcp-option=option:router,{self.config.downstream_ip}",
                f"dhcp-option=option:dns-server,{dns}",
                f"dhcp-leasefile={LEASE_PATH}",
                "no-hosts",
                "no-resolv",
                "",
            )
        )

    def _start_dnsmasq(self, downstream: str) -> None:
        if self.dnsmasq and self.dnsmasq.poll() is None:
            return
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        config_path = RUN_DIR / "dnsmasq.conf"
        config_path.write_text(self._dnsmasq_config(downstream), encoding="utf-8")
        self._run("dnsmasq", "--test", f"--conf-file={config_path}")
        self.dnsmasq = subprocess.Popen(
            ["dnsmasq", "--keep-in-foreground", f"--conf-file={config_path}"],
            text=True,
        )

    def _stop_dnsmasq(self) -> None:
        if self.dnsmasq and self.dnsmasq.poll() is None:
            self.dnsmasq.terminate()
            try:
                self.dnsmasq.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.dnsmasq.kill()
                self.dnsmasq.wait(timeout=5)
        self.dnsmasq = None

    def cleanup(
        self,
        *,
        preserve_desired: bool = False,
        preserve_trial_deadline: bool = False,
    ) -> None:
        with self.lock:
            self._stop_dnsmasq()
            if self.config.dry_run:
                self.mode = "disabled"
                if not preserve_desired:
                    self.desired_mode = "disabled"
                if not preserve_trial_deadline:
                    self.trial_deadline = None
                self.applied = False
                return

            for priority in self.RULE_PRIORITIES:
                while self._run("ip", "rule", "del", "pref", str(priority), check=False).returncode == 0:
                    pass
            self._run(
                "ip",
                "route",
                "flush",
                "table",
                str(self.config.routing_table),
                check=False,
            )

            for family, parent, child in (
                ("iptables", "DOCKER-USER", self.FILTER_CHAIN),
                ("ip6tables", "DOCKER-USER", self.FILTER6_CHAIN),
            ):
                jump = [
                    "-j",
                    child,
                    "-m",
                    "comment",
                    "--comment",
                    f"{self.COMMENT_PREFIX}:{'v6-' if family == 'ip6tables' else ''}jump",
                ]
                while self._run(family, "-C", parent, *jump, check=False).returncode == 0:
                    self._run(family, "-D", parent, *jump, check=False)
                if self._run(family, "-S", child, check=False).returncode == 0:
                    self._run(family, "-F", child, check=False)
                    self._run(family, "-X", child, check=False)

            tag = self.COMMENT_PREFIX
            nat_rule = [
                "POSTROUTING",
                "-s",
                self.config.transit_subnet,
                "-o",
                self.config.upstream_interface,
                "-j",
                "MASQUERADE",
                "-m",
                "comment",
                "--comment",
                f"{tag}:snat",
            ]
            self._delete_rule(["-t", "nat"], nat_rule)
            downstream = self._find_interface_by_mac()
            for direction in ("-o", "-i"):
                if downstream is None:
                    continue
                if direction == "-o":
                    match = [
                        "-i",
                        downstream,
                        "-o",
                        self.config.upstream_interface,
                        "-s",
                        self.config.transit_subnet,
                    ]
                else:
                    match = [
                        "-i",
                        self.config.upstream_interface,
                        "-o",
                        downstream,
                        "-d",
                        self.config.transit_subnet,
                    ]
                mss_rule = [
                    "FORWARD",
                    *match,
                    "-p",
                    "tcp",
                    "--tcp-flags",
                    "SYN,RST",
                    "SYN",
                    "-j",
                    "TCPMSS",
                    "--clamp-mss-to-pmtu",
                    "-m",
                    "comment",
                    "--comment",
                    f"{tag}:mss-{direction[-1]}",
                ]
                self._delete_rule(["-t", "mangle"], mss_rule)

            self.mode = "disabled"
            if not preserve_desired:
                self.desired_mode = "disabled"
            if not preserve_trial_deadline:
                self.trial_deadline = None
            self.applied = False

    def _health_probe(self) -> tuple[bool, str | None]:
        result = self._run(
            "curl",
            "-4",
            "-fsS",
            "--interface",
            self.config.upstream_ip,
            "--max-time",
            "10",
            "https://www.cloudflare.com/cdn-cgi/trace",
            check=False,
            timeout=15,
        )
        if result.returncode != 0:
            return False, None
        public_ip = None
        for line in result.stdout.splitlines():
            if line.startswith("ip="):
                public_ip = line.partition("=")[2]
                break
        return True, public_ip

    def apply(self, mode: str, *, recovering: bool = False) -> None:
        if mode not in {"trial", "active"}:
            raise GatewayError("Mode must be trial or active")
        if self.config.dry_run:
            raise SafetyError("Mutation is disabled while dry_run is true")

        with self.lock:
            if not recovering:
                self.desired_mode = mode
                self.trial_deadline = None
            downstream = self._find_interface_by_mac()
            errors = self.safety_errors(downstream)
            if errors:
                self.cleanup(
                    preserve_desired=True,
                    preserve_trial_deadline=recovering,
                )
                self.last_error = "; ".join(errors)
                raise SafetyError(self.last_error)
            assert downstream is not None

            self.cleanup(
                preserve_desired=True,
                preserve_trial_deadline=recovering and mode == "trial",
            )
            try:
                self._apply_policy_routing(downstream)
                self._apply_firewall(downstream)
                self._start_dnsmasq(downstream)
            except (GatewayError, OSError, subprocess.SubprocessError, ValueError) as err:
                self.cleanup(
                    preserve_desired=True,
                    preserve_trial_deadline=recovering and mode == "trial",
                )
                self.last_error = f"Activation failed: {err}"
                raise GatewayError(self.last_error) from err
            self.mode = mode
            self.applied = True
            if mode == "trial" and self.trial_deadline is None:
                self.trial_deadline = time.time() + self.config.trial_seconds
            elif mode == "active":
                self.trial_deadline = None
            self.last_error = None

    def reconcile(self) -> None:
        with self.lock:
            self.last_reconcile = time.time()
            if (
                self.desired_mode == "trial"
                and self.trial_deadline
                and time.time() >= self.trial_deadline
            ):
                self.cleanup()
                self.last_error = "Trial expired and was rolled back"
                return
            if self.desired_mode not in {"trial", "active"}:
                return
            downstream = self._find_interface_by_mac()
            errors = self.safety_errors(downstream)
            if errors:
                self.cleanup(
                    preserve_desired=True,
                    preserve_trial_deadline=True,
                )
                self.last_error = "; ".join(errors)
                return
            if (
                self.mode != self.desired_mode
                or not self._rules_installed()
                or not self.dnsmasq
                or self.dnsmasq.poll() is not None
            ):
                self.apply(self.desired_mode, recovering=True)

    def status(self) -> dict[str, object]:
        with self.lock:
            downstream = self._find_interface_by_mac()
            errors = self.safety_errors(downstream)
            healthy, public_ip = self._health_probe()
            return {
                "mode": self.mode,
                "desired_mode": self.desired_mode,
                "configured_mode": self.config.mode,
                "dry_run": self.config.dry_run,
                "management_interface": self.config.management_interface,
                "upstream_interface": self.config.upstream_interface,
                "downstream_interface": downstream,
                "downstream_present": downstream is not None,
                "rules_installed": self._rules_installed(),
                "dnsmasq_running": bool(self.dnsmasq and self.dnsmasq.poll() is None),
                "upstream_healthy": healthy,
                "public_ip": public_ip,
                "rollback_armed": self.trial_deadline is not None,
                "rollback_deadline": self.trial_deadline,
                "last_reconcile": self.last_reconcile,
                "last_error": self.last_error,
                "safety_errors": errors,
                "config": {
                    key: value
                    for key, value in asdict(self.config).items()
                    if key not in {"dns_servers"}
                },
            }

    def run_loop(self) -> None:
        if self.desired_mode in {"trial", "active"} and not self.config.dry_run:
            try:
                self.apply(self.desired_mode)
            except GatewayError as err:
                self.last_error = str(err)

        while not self.stop_event.wait(self.config.reconcile_seconds):
            try:
                self.reconcile()
            except (GatewayError, OSError, subprocess.SubprocessError, ValueError) as err:
                self.last_error = str(err)

    def stop(self) -> None:
        self.stop_event.set()
        self.cleanup()


def load_or_create_token(path: Path = TOKEN_PATH) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    path.write_text(token, encoding="utf-8")
    path.chmod(0o600)
    return token
