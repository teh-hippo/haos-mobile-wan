from __future__ import annotations

import subprocess
from collections.abc import Sequence
from typing import Protocol


DEVICE = "nmwan0"
SYNTHETIC_DEVICE_IDENTITY = "nm-lab-veth:nmwan0"
WIFI_RADIO_QUERY = ("nmcli", "-g", "WIFI-HW,WIFI", "radio")


class CommandRunner(Protocol):
    def run(
        self,
        args: list[str],
        *,
        check: bool = True,
        timeout: int = 20,
    ) -> subprocess.CompletedProcess[str]: ...


class NmcliHarnessRunner:
    """Limit veth-only Wi-Fi read virtualisation to the integration lab."""

    def __init__(self, runner: CommandRunner) -> None:
        self.runner = runner

    def run(
        self,
        args: list[str],
        *,
        check: bool = True,
        timeout: int = 20,
    ) -> subprocess.CompletedProcess[str]:
        if tuple(args) == WIFI_RADIO_QUERY:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout="enabled\nenabled\n",
                stderr="",
            )

        result = self.runner.run(args, check=check, timeout=timeout)
        if self._missing_device_path(args, result):
            result.stdout = self._with_synthetic_path(result.stdout or "")
        return result

    @staticmethod
    def _missing_device_path(
        args: Sequence[str], result: subprocess.CompletedProcess[str]
    ) -> bool:
        if result.returncode != 0:
            return False
        if len(args) < 6 or tuple(args[:2]) != ("nmcli", "-g"):
            return False
        if tuple(args[3:6]) != ("device", "show", DEVICE):
            return False
        fields = args[2].split(",")
        if not fields or fields[0] != "GENERAL.PATH":
            return False
        values = (result.stdout or "").splitlines()
        return not values or values[0].strip() in {"", "--", "*"}

    @staticmethod
    def _with_synthetic_path(stdout: str) -> str:
        lines = stdout.splitlines()
        if lines:
            lines[0] = SYNTHETIC_DEVICE_IDENTITY
        else:
            lines = [SYNTHETIC_DEVICE_IDENTITY]
        return "\n".join(lines) + ("\n" if stdout.endswith("\n") else "")
