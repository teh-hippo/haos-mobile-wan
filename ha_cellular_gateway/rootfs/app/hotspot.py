from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from .config import GatewayConfig

UrlOpen = Callable[..., object]

WIFI_ADAPTER_DISABLED = "Hotspot Wi-Fi adapter is disabled"
WIFI_NOT_ASSOCIATED = "Hotspot Wi-Fi is enabled but not associated"

_WIFI_INACTIVE_ERRORS = {
    "Upstream interface/address is not active",
    "Upstream interface is unavailable",
}


def configure_hotspot(
    config: GatewayConfig,
    *,
    enabled: bool,
    token: str | None = None,
    urlopen: UrlOpen | None = None,
) -> str | None:
    if (
        enabled
        and (
            not config.uses_wifi
            or not config.hotspot_credentials_configured
        )
    ):
        return None
    supervisor_token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN")
    action = "provisioning" if enabled else "deactivation"
    if not supervisor_token:
        return f"Hotspot Wi-Fi {action} failed: Supervisor token is unavailable"
    request = urllib.request.Request(
        _interface_url(config.upstream_interface, "update"),
        data=json.dumps(
            _payload(config, enabled=enabled),
            separators=(",", ":"),
        ).encode(),
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
        return _error(action, "Supervisor network API rejected the update", err, config)
    except urllib.error.URLError as err:
        return _error(action, "Supervisor network API is unavailable", err, config)
    except OSError as err:
        return _error(action, "Supervisor network API failed", err, config)
    return None


def interface_status(
    config: GatewayConfig,
    *,
    token: str | None = None,
    urlopen: UrlOpen | None = None,
) -> dict[str, object] | None:
    supervisor_token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN")
    if not supervisor_token:
        return None
    request = urllib.request.Request(
        _interface_url(config.upstream_interface, "info"),
        method="GET",
        headers={"Authorization": f"Bearer {supervisor_token}"},
    )
    opener = urlopen or urllib.request.urlopen
    try:
        payload = json.loads(opener(request, timeout=10).read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        err.close()
        return None
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def classify_wifi_upstream(
    config: GatewayConfig,
    errors: list[str],
    reader: Callable[[], dict[str, object] | None],
) -> list[str]:
    if not (config.uses_wifi and config.hotspot_credentials_configured):
        return errors
    if not any(error in _WIFI_INACTIVE_ERRORS for error in errors):
        return errors
    diagnostic = _wifi_diagnostic(reader())
    if diagnostic is None:
        return errors
    classified = [error for error in errors if error not in _WIFI_INACTIVE_ERRORS]
    classified.append(diagnostic)
    return classified


def _wifi_diagnostic(data: dict[str, object] | None) -> str | None:
    if data is None:
        return None
    if data.get("enabled") is False:
        return WIFI_ADAPTER_DISABLED
    if data.get("connected") is False:
        return WIFI_NOT_ASSOCIATED
    return None


def _interface_url(interface: str, action: str) -> str:
    quoted = urllib.parse.quote(interface, safe="")
    return f"http://supervisor/network/interface/{quoted}/{action}"


def _payload(config: GatewayConfig, *, enabled: bool) -> dict[str, object]:
    if not enabled:
        return {"enabled": False}
    return {
        "enabled": enabled,
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


def _error(
    action: str,
    prefix: str,
    err: Exception,
    config: GatewayConfig,
) -> str:
    detail = _supervisor_detail(err)
    label = f"Hotspot Wi-Fi {action} failed"
    if detail:
        return f"{label}: {prefix}: {_redact(detail, config)}"
    return f"{label}: {prefix}"


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
