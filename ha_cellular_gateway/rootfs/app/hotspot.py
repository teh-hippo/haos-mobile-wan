from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from .config import GatewayConfig

UrlOpen = Callable[..., object]


def provision_hotspot(
    config: GatewayConfig,
    *,
    token: str | None = None,
    urlopen: UrlOpen | None = None,
) -> str | None:
    if (
        config.upstream_mode != "hotspot_wifi"
        or config.dry_run
        or not config.hotspot_credentials_configured
    ):
        return None
    supervisor_token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN")
    if not supervisor_token:
        return "Hotspot Wi-Fi provisioning failed: Supervisor token is unavailable"
    request = urllib.request.Request(
        _interface_url(config.upstream_interface),
        data=json.dumps(_payload(config), separators=(",", ":")).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {supervisor_token}",
            "Content-Type": "application/json",
        },
    )
    opener = urlopen or urllib.request.urlopen
    try:
        opener(request, timeout=10)
    except urllib.error.HTTPError as err:
        return _error("Supervisor network API rejected the update", err, config)
    except urllib.error.URLError as err:
        return _error("Supervisor network API is unavailable", err, config)
    except OSError as err:
        return _error("Supervisor network API failed", err, config)
    return None


def _interface_url(interface: str) -> str:
    quoted = urllib.parse.quote(interface, safe="")
    return f"http://supervisor/network/interface/{quoted}/update"


def _payload(config: GatewayConfig) -> dict[str, object]:
    return {
        "enabled": True,
        "ipv4": {
            "method": "static",
            "address": [config.upstream_address],
            "nameservers": list(config.dns_servers),
        },
        "ipv6": {"method": "disabled"},
        "wifi": {
            "mode": "infrastructure",
            "auth": "wpa-psk",
            "ssid": config.hotspot_ssid,
            "psk": config.hotspot_password,
        },
    }


def _error(prefix: str, err: Exception, config: GatewayConfig) -> str:
    detail = _supervisor_detail(err)
    if detail:
        return f"Hotspot Wi-Fi provisioning failed: {prefix}: {_redact(detail, config)}"
    return f"Hotspot Wi-Fi provisioning failed: {prefix}"


def _supervisor_detail(err: Exception) -> str | None:
    if isinstance(err, urllib.error.HTTPError):
        detail = _json_error(err)
        return detail or f"HTTP {err.code}"
    reason = getattr(err, "reason", None)
    if reason is not None:
        return str(reason)
    if str(err):
        return str(err)
    return None


def _json_error(err: urllib.error.HTTPError) -> str | None:
    try:
        body = err.read()
    except OSError:
        return None
    finally:
        err.close()
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    values = [
        str(value)
        for key in ("message", "error", "reason")
        for value in [data.get(key)]
        if isinstance(value, (str, int, float))
    ]
    return ": ".join(values) if values else None


def _redact(detail: str, config: GatewayConfig) -> str:
    redacted = detail
    for secret in (config.hotspot_password,):
        if secret:
            redacted = redacted.replace(secret, "**REDACTED**")
    return redacted[:300]
