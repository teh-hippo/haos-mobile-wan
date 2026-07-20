"""Behavioural tests for :mod:`rootfs.app.gateway_probe`.

``probe_upstream`` only depends on ``engine._run``, so it is exercised here
against a minimal stand-in rather than a full ``GatewayEngine``.
"""

from __future__ import annotations

import subprocess
import types
import unittest
from collections.abc import Callable
from typing import Any

from rootfs.app.gateway_probe import probe_upstream
from rootfs.app.upstream_models import ResolvedUpstream
from test_support.process import Result

UPSTREAM = ResolvedUpstream(
    connection="wifi_hotspot",
    interface="wlan0",
    address="192.0.2.5/24",
    gateway="192.0.2.1",
)


def _engine(run: Callable[..., Any]) -> Any:
    return types.SimpleNamespace(_run=run)


class ProbeUpstreamTests(unittest.TestCase):
    def test_missing_upstream_short_circuits_without_running_anything(self) -> None:
        def _unexpected(*_args: Any, **_kwargs: Any) -> Result:
            raise AssertionError("_run must not be called when upstream is None")

        healthy, public_ip = probe_upstream(_engine(_unexpected), None)

        self.assertFalse(healthy)
        self.assertIsNone(public_ip)

    def test_successful_probe_parses_public_ip_and_uses_upstream_interface(
        self,
    ) -> None:
        calls: list[tuple[tuple[str, ...], dict[str, Any]]] = []

        def _run(*args: str, **kwargs: Any) -> Result:
            calls.append((args, kwargs))
            return Result(returncode=0, stdout="fl=1f1\nip=203.0.113.9\nts=123\n")

        healthy, public_ip = probe_upstream(_engine(_run), UPSTREAM)

        self.assertTrue(healthy)
        self.assertEqual(public_ip, "203.0.113.9")
        self.assertEqual(len(calls), 1)
        args, kwargs = calls[0]
        self.assertEqual(
            args,
            (
                "curl",
                "-4",
                "-fsS",
                "--interface",
                "192.0.2.5",
                "--max-time",
                "10",
                "https://www.cloudflare.com/cdn-cgi/trace",
            ),
        )
        self.assertEqual(kwargs, {"check": False, "timeout": 15})

    def test_successful_probe_without_ip_line_reports_healthy_with_no_ip(
        self,
    ) -> None:
        def _run(*_args: str, **_kwargs: Any) -> Result:
            return Result(returncode=0, stdout="fl=1f1\nts=123\n")

        healthy, public_ip = probe_upstream(_engine(_run), UPSTREAM)

        self.assertTrue(healthy)
        self.assertIsNone(public_ip)

    def test_non_zero_returncode_is_unhealthy_even_with_ip_line(self) -> None:
        def _run(*_args: str, **_kwargs: Any) -> Result:
            return Result(returncode=1, stdout="ip=203.0.113.9\n")

        healthy, public_ip = probe_upstream(_engine(_run), UPSTREAM)

        self.assertFalse(healthy)
        self.assertIsNone(public_ip)

    def test_os_error_is_unhealthy(self) -> None:
        def _run(*_args: str, **_kwargs: Any) -> Result:
            raise OSError("no such interface")

        healthy, public_ip = probe_upstream(_engine(_run), UPSTREAM)

        self.assertFalse(healthy)
        self.assertIsNone(public_ip)

    def test_subprocess_error_is_unhealthy(self) -> None:
        def _run(*_args: str, **_kwargs: Any) -> Result:
            raise subprocess.TimeoutExpired(cmd="curl", timeout=15)

        healthy, public_ip = probe_upstream(_engine(_run), UPSTREAM)

        self.assertFalse(healthy)
        self.assertIsNone(public_ip)


if __name__ == "__main__":
    unittest.main()
