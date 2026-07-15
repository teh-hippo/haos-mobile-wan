# HAOS Mobile WAN

Home Assistant OS app for a vendor-neutral mobile WAN gateway, with an optional
custom integration that exposes its status and safe control surface inside Home
Assistant.

The app is intentionally safe by default:

- manual boot;
- `mode: disabled`;
- `dry_run: true`;
- no forwarding, NAT, DHCP or downstream-address activation without passing
  safety checks;
- automatic management-network and single USB Ethernet discovery;
- exact transient downstream-address ownership with fail-closed cleanup;
- no `full_access` capability.

## Architecture

- `end0`: unchanged Home Assistant management network;
- `wlan0`: default iPhone hotspot upstream, with no main-table default route,
  configured manually or from masked app options;
- `ipheth`: optional experimental iPhone USB-tethering upstream, paired and
  DHCP-managed by the app without using the management Ethernet;
- USB Ethernet NIC: isolated downstream to a router WAN port;
- policy routing table 201;
- tagged `iptables-nft` rules through Docker's `DOCKER-USER`;
- dnsmasq bound only to the downstream NIC;
- fail-closed teardown and automatic recovery after transient interface loss;
- typed authenticated local API;
- optional Supervisor-discovered Home Assistant integration.

## Repository layout

- `ha_cellular_gateway/`: Home Assistant app;
- `custom_components/ha_cellular_gateway/`: optional companion integration;
- `hacs.json`: HACS metadata for the optional integration.

## Install the HAOS app

In Home Assistant:

1. Open **Settings > Apps > App store**.
2. Open the menu and select **Repositories**.
3. Add `https://github.com/teh-hippo/haos-mobile-wan`.
4. Install **HAOS Mobile WAN**.

Leave manual boot, disabled mode and dry-run enabled until the upstream and
unaddressed USB Ethernet baseline match the target HAOS host. Then follow the
[commissioning guide](ha_cellular_gateway/DOCS.md).

## Remove the HAOS app

1. Set the app back to `mode: disabled` and restart it if the gateway is still
   active.
2. Disconnect the downstream USB Ethernet cable from the router WAN port.
3. In **Settings > Apps**, stop and uninstall **HAOS Mobile WAN**.
4. If the USB Ethernet adapter will be reused, restore its HAOS IPv4 and IPv6
   profile from the disabled commissioning baseline.
5. Remove the repository entry from the app store only if you no longer want
   app updates from this repository.

Removing the HAOS app does not uninstall the optional HACS integration, but the
integration will become unavailable until a reachable gateway app is installed
again.

## Optional Home Assistant integration

The optional `ha_cellular_gateway` custom integration is separate from the HAOS
app:

- installing the app from the Home Assistant app store does **not** install the
  integration;
- installing the integration via HACS does **not** install or configure the
  app;
- the integration only works against a running HAOS Mobile WAN app API.

### Install the optional Home Assistant integration

Chosen distribution path: **HACS custom repository**. This is the smallest
supported install path for a mixed repository because HACS discovers the
integration from `custom_components/ha_cellular_gateway/` while the app remains
installable from the same repository.

| Installation parameter | Value |
|---|---|
| Repository URL | `https://github.com/teh-hippo/haos-mobile-wan` |
| HACS category | `Integration` |
| Integration domain | `ha_cellular_gateway` |

1. Install and open HACS.
2. Go to **HACS > Integrations**.
3. Open the menu, choose **Custom repositories**, then add
   `https://github.com/teh-hippo/haos-mobile-wan` as an **Integration**.
4. Find **HAOS Mobile WAN** in HACS and install it.
5. Restart Home Assistant.
6. Go to **Settings > Devices & services > Add integration** and select
   **HAOS Mobile WAN**.
7. If the app runs on the same HAOS host, prefer the Supervisor-discovered
   flow. If discovery is not available, use the manual flow with the parameters
   below.

| Configuration parameter | Required when | Value |
|---|---|---|
| App API URL | Manual setup only | Gateway app base URL, for example `http://172.30.32.1:8099` |
| API token | Manual setup only | The app token published by discovery or stored at `/data/api_token` inside the app |

### Remove the optional Home Assistant integration

1. Go to **Settings > Devices & services** and remove the **HAOS Mobile WAN**
   config entry.
2. Go to **HACS > Integrations**, uninstall **HAOS Mobile WAN**, then restart
   Home Assistant.
3. Remove the custom repository entry from HACS only if you no longer want
   integration updates from this repository.

Removing the optional integration does not remove the HAOS app or change the
gateway state.

### Entity reference

| Entity | Platform | Purpose |
|---|---|---|
| Upstream healthy | `binary_sensor` | `on` when the selected mobile upstream currently passes health checks |
| Downstream interface present | `binary_sensor` | `on` when the configured downstream adapter is present |
| Gateway rules applied | `binary_sensor` | `on` when the managed firewall and policy rules are installed |
| DHCP server running | `binary_sensor` | `on` when the downstream DHCP service is running |
| Safety checks | `binary_sensor` | `on` when all gateway safety checks pass; `errors` lists current failures |
| Mode | `sensor` | Current effective gateway mode reported by the app |
| Desired mode | `sensor` | Requested mode before or during reconciliation |
| Upstream mode | `sensor` | Active upstream strategy such as `hotspot_wifi` or `iphone_usb` |
| Upstream pairing | `sensor` | Current iPhone USB pairing state when that path is enabled |
| Downstream interface | `sensor` | Current downstream interface name |
| Public IP | `sensor` | Public IPv4 address seen through the mobile upstream |
| Last error | `sensor` | Last focused gateway error reported by the app |

### Control reference

| Control | Platform | Behaviour |
|---|---|---|
| Mode | `select` | Runtime control for `disabled` and `active` |
| Reapply gateway state | `button` | Triggers an immediate reconcile against the current app settings |

### Function reference

| Function | Details |
|---|---|
| Supervisor discovery | Auto-discovers the same-host HAOS app and refreshes a stored URL or token when the app republishes discovery |
| Manual connection flow | Connects to a local or remote gateway API with an explicit URL and token |
| Status polling | Fetches `/v1/status` every 30 seconds through a `DataUpdateCoordinator` |
| Immediate refresh after control | Refreshes state immediately after mode changes or a manual reconcile |
| Diagnostics export | Provides redacted config entry and runtime data for troubleshooting |
| Single device model | Groups all entities under one HAOS Mobile WAN gateway device entry |

### Update behaviour

- HACS updates only the optional integration. App updates still come from the
  Home Assistant app store.
- After installing or updating the integration, restart Home Assistant.
- The integration polls the gateway API every 30 seconds.
- Pressing **Reapply gateway state** or changing the **Mode** select triggers an
  immediate refresh after the API call completes.
- If the app is reinstalled or republishes discovery with a new token or URL,
  the Supervisor discovery path updates the existing entry in place.

### Use cases

- keep a gateway health summary visible on the main Home Assistant dashboard;
- alert when the mobile upstream drops or when safety checks fail closed;
- expose a direct **active** / **disabled** toggle and manual reconcile button without opening
  an SSH shell on the HAOS host.

### Automation examples

Notify when the mobile upstream is unhealthy for two minutes:

```yaml
automation:
  - alias: HAOS Mobile WAN upstream unhealthy
    triggers:
      - trigger: state
        entity_id: binary_sensor.haos_mobile_wan_upstream_healthy
        to: "off"
        for: "00:02:00"
    actions:
      - action: persistent_notification.create
        data:
          title: HAOS Mobile WAN
          message: Cellular upstream health checks are failing.
```

Notify with the current safety errors when the gateway fails closed:

```yaml
automation:
  - alias: HAOS Mobile WAN safety failure
    triggers:
      - trigger: state
        entity_id: binary_sensor.haos_mobile_wan_safety_checks
        to: "off"
    actions:
      - action: persistent_notification.create
        data:
          title: HAOS Mobile WAN safety checks failed
          message: >
            {{ state_attr('binary_sensor.haos_mobile_wan_safety_checks', 'errors')
               | join(', ') }}
```

Retry reconciliation after enabling iPhone USB trust:

```yaml
automation:
  - alias: HAOS Mobile WAN retry after iPhone trust
    triggers:
      - trigger: state
        entity_id: sensor.haos_mobile_wan_upstream_pairing
        to: "paired"
    actions:
      - action: button.press
        target:
          entity_id: button.haos_mobile_wan_reapply_gateway_state
```

### Supported hardware

| Hardware / topology | Status | Notes |
|---|---|---|
| Home Assistant OS host running the HAOS Mobile WAN app | Supported | Required for the integration to discover or reach the local API |
| Management Ethernet preserved as the main LAN uplink | Supported | The gateway app discovers and validates the sole main default route and its IPv4 address |
| Wi-Fi hotspot upstream on `wlan0` | Supported | This is the default validated upstream path. Credentials can stay in an external HAOS profile or be applied from masked app options at startup |
| USB Ethernet downstream NIC connected to a router WAN port | Supported | A single adapter is selected automatically; its host profile must have IPv4 and IPv6 disabled |
| iPhone USB tethering via dynamic `ipheth` | Experimental support | Supported by the app and surfaced by the integration, but still experimental on stock HAOS 18.1 |

### Unsupported hardware

| Hardware / topology | Why it is unsupported |
|---|---|
| Home Assistant Core, Container, or Supervised without the HAOS app | The integration only talks to the HAOS Mobile WAN app API |
| Installing the integration without a reachable gateway API | The config flow validates the API before setup |
| Connecting the downstream USB NIC to a normal LAN or switch | The gateway app serves authoritative DHCP on that interface |
| Unvalidated USB NICs, host kernels, or HAOS builds | Real hardware validation is still required per target host |
| Non-iPhone USB tethering paths | The documented USB mode is specifically the current experimental `ipheth` path |

### Limitations

- this is a custom integration distributed from a mixed repository, not a Home
  Assistant Core integration;
- the integration is a companion UI and API layer and does not replace the
  [commissioning guide](ha_cellular_gateway/DOCS.md);
- manual configuration requires access to the gateway API token;
- current self-assessment is tracked in
  [`custom_components/ha_cellular_gateway/quality_scale.yaml`](custom_components/ha_cellular_gateway/quality_scale.yaml);
- local brand assets under `custom_components/ha_cellular_gateway/brand/` cover
  this custom integration only; a future Home Assistant Core submission would
  still need the separate upstream review process.

### Repairs

- Stable repairable gateway issues are surfaced as Home Assistant Repairs
  entries for invalid state, host configuration, downstream configuration,
  policy conflicts, and upstream configuration failures.
- Transient states such as waiting for device trust, unlock, or DHCP are kept
  out of Repairs and remain visible through status entities and diagnostics.
- Fixing the underlying app or host problem clears the corresponding Repairs
  issue on the next successful coordinator refresh or unload.

### Diagnostics

- The diagnostics download includes both the stored config entry and the latest
  runtime status payload.
- Diagnostics redact the API URL, token, public IP, host addressing, interface
  names, last error text, safety errors, and USB pairing details before export.
- Structured `issues` data remains present so focused troubleshooting still has
  the repair classification from the app.

### Troubleshooting

| Problem | Check |
|---|---|
| HACS cannot find the integration | Confirm the repository was added as category **Integration**, not as an app store repository |
| The integration does not auto-discover | Confirm the HAOS app is installed on the same HAOS host and has published Supervisor discovery |
| Manual setup says it cannot connect | Verify the API URL, token, and that the app is running and bound to the expected address and port |
| The integration requests reauthentication | The app token changed; rerun the reauthentication flow with a current token |
| Entities show unavailable | Check the app logs and the **Last error** / **Safety checks** entities for the current fail-closed reason |
| The button or select appears to do nothing | The app may still be in `dry_run`, `disabled`, or failing safety checks; inspect the current mode and last error first |
| More than one USB Ethernet adapter is attached | Set the optional `downstream_mac` override to the intended router-WAN adapter |
| The app reports host-managed downstream IPv4 | Set the USB Ethernet HAOS profile to disabled IPv4 and IPv6; the app owns its runtime address |
| Branding does not appear | Local custom-integration brands require Home Assistant 2026.3+; older installs still rely on the external brands path |

## Security status

The app uses `host_network: true`, `NET_ADMIN`, `NET_RAW`, `hassio_api: true`,
`hassio_role: manager` and `usb: true`, without `full_access`, host D-Bus or
`udev`.

- `host_network` is required because the app validates and mutates the HAOS
  host firewall, routing tables and real network interfaces.
- `NET_ADMIN` is required for the app's tagged `iptables`/`ip6tables`, route
  and policy-rule ownership model and its exact transient downstream address.
- `NET_RAW` remains required because `dnsmasq` and `udhcpc` own DHCP on the
  downstream and `iphone_usb` interfaces.
- `hassio_role: manager` is required because app-managed hotspot credentials
  use the Supervisor `/network` API. `hassio_api: true` alone can publish
  discovery but cannot update a network interface.
- `usb: true` remains required for the supported `iphone_usb` path because Home
  Assistant App permissions are static per app and cannot be toggled per
  `upstream_mode`.

That static-permission model is the supported exemption for hotspot-only
deployments: `hotspot_wifi` does not use USB at runtime, but the app still
ships with the minimal shared permission set needed for the existing iPhone USB
path. If dormant USB exposure is unacceptable on a given host, this app does
not currently offer a separate hotspot-only package.

The enforced AppArmor profile is limited to the app payload, its own `/data`
state, `/run/ha-cellgw`, the `usbmuxd` runtime socket, the required `ip`,
`iptables`, `dnsmasq`, `curl`, `usbmuxd`, `idevice*`, `udhcpc` and `/bin/sh`
executables, the specific `/proc/sys/net/ipv4` checks, `/sys/class/net`,
`/sys/devices`, `ipheth` USB sysfs inspection and `/dev/bus/usb`.

## Development validation

```sh
python -m pip install --disable-pip-version-check -r requirements-test.txt mypy pyyaml

PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=ha_cellular_gateway \
  python -m unittest discover -s ha_cellular_gateway/tests -v

PYTHONDONTWRITEBYTECODE=1 \
  python -m py_compile \
  ha_cellular_gateway/rootfs/app/*.py \
  custom_components/ha_cellular_gateway/*.py

PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=ha_cellular_gateway/rootfs \
  python -c "import app.main"

PYTHONDONTWRITEBYTECODE=1 \
  pytest tests \
  --cov=custom_components/ha_cellular_gateway \
  --cov-report=term-missing \
  --cov-report=json

python - <<'PY'
from pathlib import Path
import json

threshold = 95
report = json.loads(Path("coverage.json").read_text(encoding="utf-8"))
files = sorted(
    path
    for path in report["files"]
    if path.startswith("custom_components/ha_cellular_gateway/")
)
assert files, "No integration coverage files found"
failures = []
for path in files:
    percent = report["files"][path]["summary"]["percent_covered"]
    if percent <= threshold:
        failures.append(f"{path}: {percent:.2f}%")
if failures:
    raise SystemExit(
        f"Each integration module must exceed {threshold}% coverage:\n"
        + "\n".join(failures)
    )
PY

PYTHONDONTWRITEBYTECODE=1 python -m mypy --config-file mypy.ini

python - <<'PY'
from pathlib import Path
import json
import yaml

for path in Path(".").rglob("*.json"):
    json.loads(path.read_text(encoding="utf-8"))

for pattern in ("*.yaml", "*.yml"):
    for path in Path(".").rglob(pattern):
        yaml.safe_load(path.read_text(encoding="utf-8"))

app = yaml.safe_load(
    Path("ha_cellular_gateway/config.yaml").read_text(encoding="utf-8")
)
integration = json.loads(
    Path("custom_components/ha_cellular_gateway/manifest.json").read_text(
        encoding="utf-8"
    )
)
assert app["version"] == integration["version"]
assert app["arch"] == ["aarch64"]
assert app["host_network"] is True
assert app["hassio_api"] is True
assert app["hassio_role"] == "manager"
assert app["usb"] is True
assert app["apparmor"] is True
assert app["privileged"] == ["NET_ADMIN", "NET_RAW"]
assert app.get("full_access") in (None, False)
assert app.get("host_dbus") in (None, False)
assert app.get("udev") in (None, False)
strings = json.loads(
    Path("custom_components/ha_cellular_gateway/strings.json").read_text(
        encoding="utf-8"
    )
)
runtime_translations = json.loads(
    Path("custom_components/ha_cellular_gateway/translations/en.json").read_text(
        encoding="utf-8"
    )
)
assert strings == runtime_translations
assert Path("ha_cellular_gateway/DOCS.md").exists()
assert Path("ha_cellular_gateway/translations/en.yaml").exists()

roots = (
    Path("ha_cellular_gateway/rootfs/app"),
    Path("custom_components/ha_cellular_gateway"),
)
for root in roots:
    for path in root.glob("*.py"):
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        assert line_count <= 250, f"{path} has {line_count} lines"

dockerfile = Path("ha_cellular_gateway/Dockerfile").read_text(encoding="utf-8")
assert "ARG BUILD_FROM" not in dockerfile
assert dockerfile.startswith("FROM ghcr.io/home-assistant/base:")

profile = Path("ha_cellular_gateway/apparmor.txt").read_text(encoding="utf-8")
assert "complain" not in profile
for fragment in (
    "/run/**",
    "/proc/**",
    "/sys/bus/usb/**",
    "/sys/module/**",
    "/usr/sbin/conntrack",
):
    assert fragment not in profile
for fragment in (
    "capability net_admin,",
    "capability net_raw,",
    "/run/ha-cellgw/** rwk,",
    "/run/usbmuxd rw,",
    "/run/usbmuxd/** rwk,",
    "/var/run/usbmuxd rw,",
    "/var/lib/lockdown/** rwk,",
    "/proc/sys/net/ipv4/** r,",
    "/dev/bus/usb/** rw,",
    "/sys/bus/usb/devices/** r,",
    "/sys/bus/usb/drivers/ipheth/** r,",
    "/sys/module/ipheth/** r,",
):
    assert fragment in profile
PY

apparmor_parser -QK ha_cellular_gateway/apparmor.txt

VERSION=$(python - <<'PY'
from pathlib import Path
import yaml
app = yaml.safe_load(Path("ha_cellular_gateway/config.yaml").read_text(encoding="utf-8"))
print(app["version"])
PY
)
docker buildx build \
  --platform linux/arm64 \
  --build-arg BUILD_VERSION="$VERSION" \
  --build-arg BUILD_ARCH=aarch64 \
  --file ha_cellular_gateway/Dockerfile \
  ha_cellular_gateway
```

Do not disable dry-run until the documented management, routing, IPv6 and
firewall safety gates pass. The optional iPhone USB mode also needs the app's
`usb` permission, an explicit Trust workflow on the phone, and an unmanaged
`ipheth` interface so the app owns DHCP itself.
