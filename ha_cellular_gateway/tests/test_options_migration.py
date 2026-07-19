import io
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from rootfs.app.config import KNOWN_OPTION_KEYS
from rootfs.app.options_migration import prune_legacy_options


KNOWN_OPTIONS = {
    "auto_disable_minutes": 30,
    "mobile_connection": "Wi-Fi hotspot",
    "hotspot_ssid": "Phone",
    "hotspot_password": "supersecret",
    "downstream_mac": "00:11:22:33:44:55",
    "router_address": "192.168.90.1/24",
    "upstream_interface": "wlan0",
    "upstream_address": "172.20.10.4/28",
    "upstream_gateway": "172.20.10.1",
}

LEGACY_OPTIONS = {
    **KNOWN_OPTIONS,
    "enabled": False,
    "legacy_wifi_migration": "Manual cleanup",
    "mode": "gateway",
    "dry_run": False,
    "management_interface": "end0",
    "management_address": "192.168.1.2/24",
    "upstream_mode": "wifi",
    "upstream_ssid": "OldPhone",
    "transit_subnet": "192.168.80.0/24",
    "dhcp_start": "192.168.80.2",
    "dhcp_end": "192.168.80.254",
    "dns_servers": ["1.1.1.1"],
    "routing_table": 201,
    "trial_seconds": 300,
    "api_bind": "172.30.32.1",
    "api_port": 8099,
}


def _write_options(directory: str, payload: object) -> Path:
    path = Path(directory) / "options.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class PruneLegacyOptionsTests(unittest.TestCase):
    def test_known_option_keys_match_schema(self) -> None:
        self.assertEqual(
            KNOWN_OPTION_KEYS,
            frozenset(
                {
                    "auto_disable_minutes",
                    "mobile_connection",
                    "hotspot_ssid",
                    "hotspot_password",
                    "downstream_mac",
                    "router_address",
                    "upstream_interface",
                    "upstream_address",
                    "upstream_gateway",
                }
            ),
        )

    def test_prunes_legacy_keys_preserving_known_values(self) -> None:
        calls: list[tuple[urllib.request.Request, object]] = []

        def urlopen(request, **kwargs):
            calls.append((request, kwargs.get("timeout")))
            return object()

        with tempfile.TemporaryDirectory() as directory:
            path = _write_options(directory, LEGACY_OPTIONS)
            error = prune_legacy_options(
                token="token", urlopen=urlopen, options_path=path
            )

        self.assertIsNone(error)
        self.assertEqual(len(calls), 1)
        request, timeout = calls[0]
        assert isinstance(request, urllib.request.Request)
        self.assertEqual(
            request.full_url, "http://supervisor/addons/self/options"
        )
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer token")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(timeout, 10)
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body, {"options": KNOWN_OPTIONS})
        self.assertEqual(set(body["options"]), set(KNOWN_OPTION_KEYS))

    def test_no_post_when_only_known_keys_present(self) -> None:
        calls: list[urllib.request.Request] = []
        with tempfile.TemporaryDirectory() as directory:
            path = _write_options(directory, KNOWN_OPTIONS)
            error = prune_legacy_options(
                token="token",
                urlopen=lambda request, **kwargs: calls.append(request),
                options_path=path,
            )
        self.assertIsNone(error)
        self.assertEqual(calls, [])

    def test_missing_token_argument_skips(self) -> None:
        calls: list[urllib.request.Request] = []
        with tempfile.TemporaryDirectory() as directory:
            path = _write_options(directory, LEGACY_OPTIONS)
            error = prune_legacy_options(
                token="",
                urlopen=lambda request, **kwargs: calls.append(request),
                options_path=path,
            )
        self.assertIsNone(error)
        self.assertEqual(calls, [])

    def test_missing_env_token_skips(self) -> None:
        calls: list[urllib.request.Request] = []
        with tempfile.TemporaryDirectory() as directory:
            path = _write_options(directory, LEGACY_OPTIONS)
            with mock.patch.dict(os.environ, {}, clear=True):
                error = prune_legacy_options(
                    urlopen=lambda request, **kwargs: calls.append(request),
                    options_path=path,
                )
        self.assertIsNone(error)
        self.assertEqual(calls, [])

    def test_uses_env_token_when_argument_omitted(self) -> None:
        calls: list[urllib.request.Request] = []
        with tempfile.TemporaryDirectory() as directory:
            path = _write_options(directory, LEGACY_OPTIONS)
            with mock.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "envtok"}):
                error = prune_legacy_options(
                    urlopen=lambda request, **kwargs: calls.append(request),
                    options_path=path,
                )
        self.assertIsNone(error)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].get_header("Authorization"), "Bearer envtok")

    def test_missing_file_skips(self) -> None:
        calls: list[urllib.request.Request] = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            error = prune_legacy_options(
                token="token",
                urlopen=lambda request, **kwargs: calls.append(request),
                options_path=path,
            )
        self.assertIsNone(error)
        self.assertEqual(calls, [])

    def test_non_dict_options_skip(self) -> None:
        calls: list[urllib.request.Request] = []
        with tempfile.TemporaryDirectory() as directory:
            path = _write_options(directory, ["not", "a", "dict"])
            error = prune_legacy_options(
                token="token",
                urlopen=lambda request, **kwargs: calls.append(request),
                options_path=path,
            )
        self.assertIsNone(error)
        self.assertEqual(calls, [])

    def test_malformed_json_skips(self) -> None:
        calls: list[urllib.request.Request] = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "options.json"
            path.write_text("{not json", encoding="utf-8")
            error = prune_legacy_options(
                token="token",
                urlopen=lambda request, **kwargs: calls.append(request),
                options_path=path,
            )
        self.assertIsNone(error)
        self.assertEqual(calls, [])

    def test_http_error_returns_message_without_secrets(self) -> None:
        def urlopen(request, **kwargs):
            raise urllib.error.HTTPError(
                request.full_url, 400, "Bad Request", {}, io.BytesIO(b"")
            )

        with tempfile.TemporaryDirectory() as directory:
            path = _write_options(directory, LEGACY_OPTIONS)
            error = prune_legacy_options(
                token="token", urlopen=urlopen, options_path=path
            )
        assert error is not None
        self.assertIn("options-migration", error)
        self.assertNotIn("supersecret", error)

    def test_url_error_returns_message(self) -> None:
        def urlopen(request, **kwargs):
            raise urllib.error.URLError("supervisor down")

        with tempfile.TemporaryDirectory() as directory:
            path = _write_options(directory, LEGACY_OPTIONS)
            error = prune_legacy_options(
                token="token", urlopen=urlopen, options_path=path
            )
        assert error is not None
        self.assertIn("options-migration", error)

    def test_os_error_returns_message(self) -> None:
        def urlopen(request, **kwargs):
            raise OSError("socket exploded")

        with tempfile.TemporaryDirectory() as directory:
            path = _write_options(directory, LEGACY_OPTIONS)
            error = prune_legacy_options(
                token="token", urlopen=urlopen, options_path=path
            )
        assert error is not None
        self.assertIn("options-migration", error)


if __name__ == "__main__":
    unittest.main()
