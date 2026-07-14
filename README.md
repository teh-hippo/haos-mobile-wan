# HAOS Mobile WAN

Home Assistant OS app for a vendor-neutral mobile WAN gateway, with an optional
custom integration that exposes its status and safe control surface inside Home
Assistant.

The app is intentionally safe by default:

- manual boot;
- `mode: disabled`;
- `dry_run: true`;
- no route, firewall, NAT or DHCP mutation without passing safety checks;
- no `full_access` capability.

## Architecture

- `end0`: unchanged Home Assistant management network;
- `wlan0`: default iPhone hotspot upstream, with no main-table default route;
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

1. Open **Settings > Add-ons > Add-on store**.
2. Open the menu and select **Repositories**.
3. Add `https://github.com/teh-hippo/haos-mobile-wan`.
4. Install **HAOS Mobile WAN**.

Leave manual boot, disabled mode and dry-run enabled until every interface and
address has been configured for the target HAOS host. Then follow the
[commissioning guide](ha_cellular_gateway/DOCS.md).

## Optional Home Assistant integration

The optional `ha_cellular_gateway` custom integration is separate from the HAOS
app:

- installing the app from the Home Assistant add-on store does **not** install
  the integration;
- installing the integration via HACS does **not** install or configure the app;
- the integration only works against a running HAOS Mobile WAN app API.

### Install the optional Home Assistant integration

Chosen distribution path: **HACS custom repository**. This is the smallest
supported install path that keeps the mixed app + integration repository
directly installable without repackaging.

| Installation parameter | Value |
|---|---|
| Repository URL | `https://github.com/teh-hippo/haos-mobile-wan` |
| HACS category | `Integration` |
| Integration domain | `ha_cellular_gateway` |
| Home Assistant version for local brand assets | 2026.3+ |

1. Install and open HACS.
2. Go to **HACS > Integrations**.
3. Open the menu, choose **Custom repositories**, then add
   `https://github.com/teh-hippo/haos-mobile-wan` as an **Integration**.
4. Find **HAOS Mobile WAN** in HACS and install it.
5. Restart Home Assistant.
6. Go to **Settings > Devices & services > Add integration** and select
   **HAOS Mobile WAN**.
7. If the app runs on the same HAOS host, prefer the Supervisor-discovered flow.
   If discovery is not available, use the manual flow with the parameters below.

| Configuration parameter | Required when | Value |
|---|---|---|
| App API URL | Manual setup only | Gateway app base URL, for example `http://172.30.32.1:8099` |
| API token | Manual setup only | The app token published by discovery or stored at `/data/api_token` inside the app |

### Remove the optional Home Assistant integration

1. Go to **Settings > Devices & services** and remove the **HAOS Mobile WAN**
   config entry.
2. Go to **HACS > Integrations**, uninstall **HAOS Mobile WAN**, then restart
   Home Assistant.
3. If you no longer want HACS to offer updates from this repository, remove the
   custom repository entry as well.

Removing the integration does not remove the HAOS app or change gateway state.

### Entity reference

| Entity | Platform | Purpose |
|---|---|---|
| Cellular upstream | `binary_sensor` | `on` when the selected mobile upstream currently passes health checks |
| Downstream NIC | `binary_sensor` | `on` when the configured downstream adapter is present |
| Gateway rules | `binary_sensor` | `on` when the managed firewall and policy rules are installed |
| Gateway DHCP | `binary_sensor` | `on` when the downstream DHCP service is running |
| Rollback armed | `binary_sensor` | `on` while a trial rollback deadline is armed |
| Safety checks | `binary_sensor` | `on` when all gateway safety checks pass; `errors` attribute lists failures |
| Mode | `sensor` | Current effective gateway mode reported by the app |
| Desired mode | `sensor` | Requested mode before or during reconciliation |
| Upstream mode | `sensor` | Active upstream strategy such as `hotspot_wifi` or `iphone_usb` |
| Upstream pairing | `sensor` | iPhone USB pairing state when that path is enabled |
| Downstream interface | `sensor` | Current downstream interface name |
| Cellular public IP | `sensor` | Public IPv4 address seen through the mobile upstream |
| Last error | `sensor` | Last focused gateway error reported by the app |
| Mode | `select` | Safe runtime control limited to `disabled` and `trial` |
| Reapply gateway state | `button` | Triggers an immediate reconcile against the current app settings |

### Function reference

| Function | Details |
|---|---|
| Supervisor discovery | Auto-discovers the same-host HAOS app and refreshes stored URL/token when the app republishes discovery |
| Manual connection flow | Connects to a local or remote gateway API with an explicit URL and token |
| Status polling | Fetches `/v1/status` every 30 seconds through a `DataUpdateCoordinator` |
| Immediate refresh after control | Refreshes state immediately after mode changes or a manual reconcile |
| Diagnostics export | Provides redacted config entry and runtime data for troubleshooting |
| Single device model | Groups all entities under one HAOS Mobile WAN gateway device entry |

### Update behaviour

- HACS updates only the optional integration. App updates still come from the
  Home Assistant add-on store.
- After installing or updating the integration, restart Home Assistant.
- The integration polls the gateway API every 30 seconds.
- Pressing **Reapply gateway state** or changing the **Mode** select triggers an
  immediate refresh after the API call completes.
- If the app is reinstalled or republishes discovery with a new token or URL,
  the Supervisor discovery path updates the existing entry in place.

### Use cases

- keep a gateway health summary visible on the main Home Assistant dashboard;
- alert when the mobile upstream drops or when safety checks fail closed;
- confirm that a trial window is still armed before testing a new WAN path;
- expose a guarded **trial** toggle and manual reconcile button without opening
  an SSH shell on the HAOS host.

### Automation examples

Notify when the mobile upstream is unhealthy for two minutes:

```yaml
automation:
  - alias: HAOS Mobile WAN upstream unhealthy
    triggers:
      - trigger: state
        entity_id: binary_sensor.haos_mobile_wan_cellular_upstream
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
        to: paired
    actions:
      - action: button.press
        target:
          entity_id: button.haos_mobile_wan_reapply_gateway_state
```

### Supported hardware

| Hardware / topology | Status | Notes |
|---|---|---|
| Home Assistant OS host running the HAOS Mobile WAN app | Supported | Required for the integration to discover or reach the local API |
| Management Ethernet preserved as the main LAN uplink | Supported | The gateway app validates this baseline and the integration reports its status |
| Wi-Fi hotspot upstream on `wlan0` | Supported | This is the default validated upstream path |
| USB Ethernet downstream NIC connected to a router WAN port | Supported | Required for the isolated downstream path |
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

- this is still a custom integration distributed from a mixed repository, not a
  Home Assistant Core integration;
- the integration is a companion UI/API layer and does not replace the
  [commissioning guide](ha_cellular_gateway/DOCS.md);
- the **Mode** select intentionally exposes only `disabled` and `trial`, not
  `active`, to keep the high-risk steady-state transition outside this optional
  control surface;
- manual configuration requires access to the gateway API token;
- current quality-scale gaps are tracked in
  [`custom_components/ha_cellular_gateway/quality_scale.yaml`](custom_components/ha_cellular_gateway/quality_scale.yaml);
- local brand assets under `brand/` cover current custom-integration installs on
  Home Assistant 2026.3+, but any future Home Assistant Core submission would
  still need the separate upstream docs/core/brands review process.

### Troubleshooting

| Problem | Check |
|---|---|
| HACS cannot find the integration | Confirm the repository was added as category **Integration**, not as an add-on repository |
| The integration does not auto-discover | Confirm the HAOS app is installed on the same HAOS host and has published Supervisor discovery |
| Manual setup says it cannot connect | Verify the API URL, token, and that the app is running and bound to the expected address/port |
| Entities show unavailable | Check the app logs and the **Last error** / **Safety checks** entities for the current fail-closed reason |
| The button or select appears to do nothing | The app may still be in `dry_run`, `disabled`, or failing safety checks; inspect the current mode and last error first |
| Branding does not appear | Local custom-integration brands require Home Assistant 2026.3+; older installs still rely on the external brands path |

## Development validation

```sh
python -m pip install --disable-pip-version-check -r requirements-test.txt pyyaml

PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=ha_cellular_gateway \
  python -m unittest discover -s ha_cellular_gateway/tests -v

PYTHONDONTWRITEBYTECODE=1 \
  pytest tests \
  --cov=custom_components/ha_cellular_gateway \
  --cov-report=term-missing \
  --cov-report=json

PYTHONDONTWRITEBYTECODE=1 python -m py_compile \
  ha_cellular_gateway/rootfs/app/*.py \
  custom_components/ha_cellular_gateway/*.py

PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=ha_cellular_gateway/rootfs \
  python -c "import app.main"

python - <<'PY'
from pathlib import Path
import json
import yaml

app = yaml.safe_load(Path("ha_cellular_gateway/config.yaml").read_text(encoding="utf-8"))
integration = json.loads(
    Path("custom_components/ha_cellular_gateway/manifest.json").read_text(
        encoding="utf-8"
    )
)
assert app["version"] == integration["version"]
assert not Path("custom_components/ha_cellular_gateway/strings.json").exists()
assert Path("ha_cellular_gateway/DOCS.md").exists()
assert Path("ha_cellular_gateway/translations/en.yaml").exists()

for path in Path(".").rglob("*.json"):
    json.loads(path.read_text(encoding="utf-8"))

for pattern in ("*.yaml", "*.yml"):
    for path in Path(".").rglob(pattern):
        yaml.safe_load(path.read_text(encoding="utf-8"))

for path in Path("ha_cellular_gateway/rootfs/app").glob("*.py"):
    line_count = len(path.read_text(encoding="utf-8").splitlines())
    assert line_count <= 300, f"{path} has {line_count} lines"

dockerfile = Path("ha_cellular_gateway/Dockerfile").read_text(encoding="utf-8")
assert "ARG BUILD_FROM" not in dockerfile
assert dockerfile.startswith("FROM ghcr.io/home-assistant/base:")
PY
```

Do not disable dry-run until the documented management, routing, IPv6 and
firewall safety gates pass. The optional iPhone USB mode also needs the app's
`usb` permission, an explicit Trust workflow on the phone, and an unmanaged
`ipheth` interface so the app owns DHCP itself.
