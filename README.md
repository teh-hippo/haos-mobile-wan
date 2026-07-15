# HAOS Mobile WAN

HAOS Mobile WAN lets Home Assistant OS provide a fallback Internet connection
to your router during a fixed-line outage.

It supports:

- a phone Wi-Fi hotspot;
- iPhone USB tethering;
- automatic USB-preferred Wi-Fi fallback;
- an isolated USB Ethernet connection from HAOS to the router WAN.

The traffic path is simple:

```text
Phone -> Home Assistant OS -> USB Ethernet -> Router WAN -> Home network
```

Home Assistant keeps using its normal management Ethernet connection. Mobile
traffic is handled through a separate routing table and cannot fall back
through the management network.

## How it works

The app connects HAOS to the selected mobile connection and offers one DHCP
lease to the router WAN. When enabled, it adds the router-facing address,
policy routing, forwarding, NAT and DHCP needed to carry traffic to the phone.

The gateway fails closed. If the mobile connection, router adapter, firewall or
routing state becomes unsafe, it removes forwarding and waits for the problem
to clear. It only removes addresses, routes and firewall rules that it owns.

With **USB (iPhone), Wi-Fi fallback** selected, the app:

1. uses iPhone USB while trust, `ipheth` and DHCP are ready;
2. switches to the configured Wi-Fi hotspot when USB is unavailable;
3. returns to USB when it becomes ready again.

Internet health checks are reported for diagnostics. This release switches
sources based on connection readiness, not an external connectivity probe.

## Install the HAOS app

1. Open **Settings > Apps > App store**.
2. Open the menu and select **Repositories**.
3. Add `https://github.com/teh-hippo/haos-mobile-wan`.
4. Install **HAOS Mobile WAN**.

The app starts disabled and uses manual boot. Before enabling it:

1. choose a **Mobile connection**;
2. optionally enter the Wi-Fi hotspot name and password;
3. prepare one USB Ethernet adapter for the router WAN;
4. follow the [commissioning guide](ha_cellular_gateway/DOCS.md).

The normal form contains only the settings needed for everyday use. Interface,
address and adapter overrides remain available under unused optional settings.

## Remove the HAOS app

1. Turn **Enabled** off.
2. Allow the app to reconcile or stop it cleanly.
3. Disconnect the router WAN cable from the HAOS USB Ethernet adapter.
4. Uninstall **HAOS Mobile WAN** from **Settings > Apps**.
5. Restore the USB Ethernet HAOS profile if the adapter will be reused.

Removing the app does not remove the optional HACS integration.

## Optional Home Assistant integration

The optional integration adds dashboard entities, Repairs, diagnostics and
runtime control. The app remains fully usable without it.

Installing the app does not install the integration, and installing the
integration does not install the app.

### Install the optional Home Assistant integration

1. Install [HACS](https://www.hacs.xyz/) if required.
2. In HACS, add this repository as a custom **Integration** repository.
3. Install **HAOS Mobile WAN**.
4. Restart Home Assistant.

When the app and integration run on the same HAOS host, Supervisor discovery
creates or updates the integration entry automatically.

### Remove the optional Home Assistant integration

1. Remove **HAOS Mobile WAN** from **Settings > Devices & services**.
2. Uninstall it from HACS.
3. Restart Home Assistant.

The HAOS app continues operating independently.

### Entity reference

| Entity | Platform | Purpose |
|---|---|---|
| Upstream healthy | `binary_sensor` | Whether the selected mobile connection passed its latest Internet health check |
| Downstream interface present | `binary_sensor` | Whether the router-facing USB Ethernet adapter is present |
| Gateway rules applied | `binary_sensor` | Whether forwarding, NAT and policy routing are active |
| DHCP server running | `binary_sensor` | Whether the router WAN DHCP service is running |
| Safety checks | `binary_sensor` | Whether current host and network checks pass |
| Mobile connection | `sensor` | Configured Wi-Fi, USB or USB-preferred strategy |
| Active connection | `sensor` | Wi-Fi hotspot or USB (iPhone) currently carrying gateway traffic |
| USB pairing | `sensor` | Current iPhone trust, interface and DHCP state |
| Downstream interface | `sensor` | Selected router-facing interface |
| Public IP | `sensor` | Public IPv4 address seen through the mobile connection |
| Last error | `sensor` | Latest focused gateway error |

### Control reference

| Control | Platform | Behaviour |
|---|---|---|
| Enabled | `switch` | Enables or disables gateway service to the router |
| Reapply gateway state | `button` | Runs reconciliation immediately |

The switch represents user intent. If safety checks fail, it stays enabled
while the gateway removes forwarding and retries automatically.
It controls the current app process; the saved app option controls startup
state after an app restart.

### Function reference

| Function | Details |
|---|---|
| Supervisor discovery | Finds the same-host app and refreshes its URL or token |
| Manual setup | Connects to a reachable app API using an explicit URL and token |
| Status polling | Refreshes app status every 30 seconds |
| Immediate refresh | Updates entities after a switch or button action |
| Repairs | Surfaces stable configuration and ownership failures |
| Diagnostics | Exports redacted integration and runtime data |

### Update behaviour

- App updates come from the Home Assistant app store.
- Integration updates come from HACS.
- App setting changes require an app restart.
- Integration code updates require a Home Assistant restart.
- Version 0.4.0 requires a coordinated app and integration update; follow the
  [upgrade steps](ha_cellular_gateway/DOCS.md#upgrade-to-040).

### Use cases

- keep the home network online through a phone during an ISP outage;
- prefer the lower-latency iPhone USB connection while retaining Wi-Fi
  fallback;
- alert when the mobile connection or gateway safety checks fail;
- enable or disable the gateway from Home Assistant without using SSH.

### Automation examples

Notify when the gateway is enabled but no rules are applied for two minutes:

```yaml
automation:
  - alias: Mobile WAN unavailable
    triggers:
      - trigger: state
        entity_id: binary_sensor.haos_mobile_wan_gateway_rules_applied
        to: "off"
        for: "00:02:00"
    conditions:
      - condition: state
        entity_id: switch.haos_mobile_wan_enabled
        state: "on"
    actions:
      - action: persistent_notification.create
        data:
          title: Mobile WAN unavailable
          message: Check the HAOS Mobile WAN safety and connection entities.
```

Retry immediately after accepting iPhone trust:

```yaml
automation:
  - alias: Reapply Mobile WAN after iPhone trust
    triggers:
      - trigger: state
        entity_id: sensor.haos_mobile_wan_usb_pairing
        to: "paired"
    actions:
      - action: button.press
        target:
          entity_id: button.haos_mobile_wan_reapply_gateway_state
```

### Supported hardware

| Hardware | Status |
|---|---|
| Home Assistant OS on `aarch64` | Supported |
| Phone Wi-Fi hotspot on `wlan0` | Supported |
| One USB Ethernet adapter for the router WAN | Supported |
| iPhone USB tethering through `ipheth` | Experimental |
| USB-preferred Wi-Fi fallback | Supported with the current iPhone USB path |

### Unsupported hardware

| Hardware or topology | Reason |
|---|---|
| Home Assistant Core or Container without the HAOS app | The gateway requires HAOS host networking and Supervisor |
| A downstream adapter connected to a normal LAN or switch network | The app serves authoritative DHCP on that interface |
| Generic Android or RNDIS USB tethering | Not implemented yet; tracked in [issue #96](https://github.com/teh-hippo/haos-mobile-wan/issues/96) |
| Multiple router-facing USB adapters without a MAC override | The app will not guess which adapter to use |

### Limitations

- iPhone USB requires Personal Hotspot, an unlocked phone and accepted trust;
- automatic failover reacts to source readiness, not Internet health;
- only IPv4 gateway service is supported;
- the optional integration is custom and distributed through HACS;
- physical networking still needs to be commissioned for each HAOS host.

### Repairs

Stable failures create Home Assistant Repairs entries for invalid saved state,
host safety, router adapter selection, policy conflicts, USB preparation and
Wi-Fi profile configuration.

Temporary states such as waiting for the phone, trust or DHCP remain in the
entities and diagnostics instead of creating persistent Repairs.

### Diagnostics

Diagnostics include the latest app status and structured issue information.
They redact credentials, API details, public addresses, host addressing,
interface names and iPhone identifiers.

### Troubleshooting

| Problem | Check |
|---|---|
| The gateway remains inactive while Enabled is on | Review **Safety checks** and **Last error** |
| USB is not selected | Unlock the iPhone, enable Personal Hotspot, accept Trust and check `ipheth` |
| Wi-Fi fallback is unavailable | Check the Wi-Fi hotspot profile and app credentials, then restart the app |
| The router receives no WAN lease | Confirm the router-facing USB adapter has HAOS IPv4 and IPv6 disabled |
| More than one USB Ethernet adapter is attached | Set the optional router adapter MAC address |
| Home Assistant becomes unreachable | Disable the app and verify the management Ethernet remains the only main default route |
| HACS cannot find the integration | Add the repository as category **Integration**, not as an app repository |

## Safety and security

The app uses `host_network`, `NET_ADMIN`, `NET_RAW`, Supervisor manager access
and USB access because it manages real HAOS interfaces, policy routing,
firewall rules, DHCP and optional iPhone pairing. It does not use
`full_access`, host D-Bus or `udev`.

An enforced AppArmor profile limits access to the required networking tools,
USB paths, sysfs entries and app-owned runtime data. The local API uses a
generated bearer token and binds to the Supervisor-side host address.

## Development

The existing validation workflow runs app tests, integration coverage, Python
compilation, import checks, mypy, metadata validation, AppArmor parsing and an
`aarch64` image build. See
[`.github/workflows/validate.yml`](.github/workflows/validate.yml) for the
authoritative commands.

The primary local checks are:

```sh
PYTHONPATH=ha_cellular_gateway \
  python -m unittest discover -s ha_cellular_gateway/tests -v

PYTHONPATH=ha_cellular_gateway \
  python -m py_compile \
    ha_cellular_gateway/rootfs/app/*.py \
    custom_components/ha_cellular_gateway/*.py

PYTHONPATH=ha_cellular_gateway/rootfs python -c "import app.main"
```
