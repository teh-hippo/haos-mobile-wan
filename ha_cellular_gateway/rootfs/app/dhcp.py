from __future__ import annotations

import ipaddress
import subprocess
from pathlib import Path

from .command import RunCommand, stop_process
from .config import LEASE_PATH, RUN_DIR, GatewayConfig


class DnsmasqService:
    def __init__(
        self,
        config: GatewayConfig,
        run: RunCommand,
        *,
        run_dir: Path = RUN_DIR,
        lease_path: Path = LEASE_PATH,
    ) -> None:
        self.config = config
        self.run = run
        self.run_dir = run_dir
        self.lease_path = lease_path
        self.process: subprocess.Popen[str] | None = None

    @property
    def running(self) -> bool:
        return bool(self.process and self.process.poll() is None)

    def render_config(self, downstream: str) -> str:
        netmask = ipaddress.ip_network(self.config.transit_subnet).netmask
        return "\n".join(
            (
                f"interface={downstream}",
                "bind-dynamic",
                f"listen-address={self.config.downstream_ip}",
                "port=0",
                "dhcp-authoritative",
                (
                    f"dhcp-range={self.config.dhcp_start},{self.config.dhcp_end},"
                    f"{netmask},5m"
                ),
                f"dhcp-option=option:router,{self.config.downstream_ip}",
                (
                    "dhcp-option=option:dns-server,"
                    + ",".join(self.config.dns_servers)
                ),
                f"dhcp-leasefile={self.lease_path}",
                "no-hosts",
                "no-resolv",
                "",
            )
        )

    def start(self, downstream: str) -> None:
        if self.running:
            return
        self.run_dir.mkdir(parents=True, exist_ok=True)
        config_path = self.run_dir / "dnsmasq.conf"
        config_path.write_text(
            self.render_config(downstream),
            encoding="utf-8",
        )
        self.run("dnsmasq", "--test", f"--conf-file={config_path}")
        self.process = subprocess.Popen(
            ["dnsmasq", "--keep-in-foreground", f"--conf-file={config_path}"],
            text=True,
        )

    def stop(self) -> None:
        stop_process(self.process)
        self.process = None
