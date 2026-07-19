# HAOS Mobile WAN

HAOS Mobile WAN lets Home Assistant OS provide a fallback Internet connection
to your router during a fixed-line outage.

It supports:

- a phone Wi-Fi hotspot;
- iPhone USB tethering;
- generic Android RNDIS, CDC and Ethernet-style USB tethering;
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
lease to the router WAN. While the add-on runs, it adds the router-facing
address, policy routing, forwarding, NAT and DHCP needed to carry traffic to
the phone. Running also grants temporary, exclusive control of the selected
dedicated mobile adapters.

The gateway fails closed. If the mobile connection, router adapter, firewall or
routing state becomes unsafe, it removes forwarding and waits for the problem
to clear. It only removes addresses, routes and firewall rules that it owns.

With **USB (iPhone), Wi-Fi fallback** selected, the app:

1. uses iPhone USB while trust, `ipheth` and the NetworkManager lease are ready;
2. switches to the configured Wi-Fi hotspot when USB is unavailable;
3. returns to USB when it becomes ready again.

The generic USB modes use the same selection and failover flow for Android
RNDIS, CDC Ethernet, CDC NCM and compatible USB dongles. Apple trust,
`usbmuxd` and `ipheth` remain isolated to the iPhone modes.

The app creates temporary NetworkManager profiles for the selected USB and
Wi-Fi paths. NetworkManager owns their addresses and leases; the app owns the
profiles only while running and removes them when the add-on stops.

Internet health checks are reported for diagnostics. This release switches
sources based on connection readiness, not an external connectivity probe.

## Install the HAOS app

1. Open **Settings > Apps > App store**.
2. Open the menu and select **Repositories**.
3. Add `https://github.com/teh-hippo/haos-mobile-wan`.
4. Install **HAOS Mobile WAN**.

The app uses manual boot and activates the gateway as soon as it starts.
Before starting it:

1. choose a **Mobile connection**;
2. set the automatic stop delay, or use `0` to keep the add-on running;
3. enter the Wi-Fi hotspot name and password when Wi-Fi is selected;
4. reserve a dedicated, non-management Wi-Fi adapter when Wi-Fi is selected;
5. prepare one USB Ethernet adapter for the router WAN;
6. follow the [commissioning guide](ha_cellular_gateway/DOCS.md).

The normal form contains only the settings needed for everyday use. Interface,
address and adapter overrides remain available under unused optional settings.

## Remove the HAOS app

1. Stop the add-on.
2. Allow the app to release its network state as it stops.
3. Disconnect the router WAN cable from the HAOS USB Ethernet adapter.
4. Uninstall **HAOS Mobile WAN** from **Settings > Apps**.
5. Restore the USB Ethernet HAOS profile if the adapter will be reused.

## Home Assistant entities (MQTT)

The add-on publishes a **HAOS Mobile WAN** device and its entities through
Home Assistant MQTT discovery. It needs the Home Assistant MQTT integration and
an MQTT broker, such as the Mosquitto broker add-on.

Enable the MQTT integration and broker, then start the add-on. The device and
its entities appear automatically and refresh while the add-on runs, so no
reload is needed after an add-on update. Some diagnostic entities are disabled
by default; enable them from the device page when needed.

### Dashboard example

Add the entities to any built-in card, for example an `entities` card:

```yaml
type: entities
title: HAOS Mobile WAN
entities:
  - entity: sensor.haos_mobile_wan_gateway_state
    name: Gateway state
  - entity: sensor.haos_mobile_wan_health
    name: Health
  - entity: sensor.haos_mobile_wan_connection_method
    name: Connection method
  - entity: sensor.haos_mobile_wan_connected_via
    name: Connected via
  - entity: binary_sensor.haos_mobile_wan_internet_available
    name: Internet available
  - entity: sensor.haos_mobile_wan_usb_status
    name: USB status
  - entity: sensor.haos_mobile_wan_public_ip
    name: Public IP
```

Fresh installs normally create the USB entity as
`sensor.haos_mobile_wan_usb_status`. Existing installs keep the entity ID
already stored in Home Assistant, commonly
`sensor.haos_mobile_wan_usb_pairing`; select it from the device page if the
example ID differs.

### Entity reference

| Entity | Platform | Purpose |
|---|---|---|
| Internet available | `binary_sensor` | Whether the selected mobile connection passed its latest Internet health check |
| Downstream interface present | `binary_sensor` | Whether the router-facing USB Ethernet adapter is present |
| Gateway rules applied | `binary_sensor` | Whether forwarding, NAT and policy routing are active |
| DHCP server running | `binary_sensor` | Whether the router WAN DHCP service is running |
| Gateway state | `sensor` | Waiting, connecting, connected or error |
| Health | `sensor` | Healthy or attention needed, with actionable issues as attributes |
| Connection method | `sensor` | Configured Wi-Fi, USB or USB-preferred strategy |
| Connected via | `sensor` | Wi-Fi hotspot, USB (iPhone) or USB (generic) currently carrying gateway traffic, or not connected |
| USB status | `sensor` | Current USB trust/readiness, interface and DHCP state |
| Downstream interface | `sensor` | Selected router-facing interface, or not present |
| Public IP | `sensor` | Public IPv4 address seen through the mobile connection, or not connected |

### Control reference

The MQTT entities are status-only for monitoring. There are no Home Assistant
control entities; control the gateway through the add-on options.

### Use cases

- keep the home network online through a phone during an ISP outage;
- prefer the lower-latency iPhone USB connection while retaining Wi-Fi
  fallback;
- alert when gateway Health needs attention;
- monitor the mobile connection and gateway health from Home Assistant.

### Automation examples

Notify when gateway Health needs attention:

```yaml
automation:
  - alias: Mobile WAN needs attention
    triggers:
      - trigger: state
        entity_id: sensor.haos_mobile_wan_health
        to: "Attention needed"
    actions:
      - action: persistent_notification.create
        data:
          title: HAOS Mobile WAN needs attention
          message: >-
            {{ state_attr('sensor.haos_mobile_wan_health', 'issues')
               | join('; ') }}
```

### Supported hardware

| Hardware | Status |
|---|---|
| Home Assistant OS on `aarch64` | Supported |
| Phone Wi-Fi hotspot on a dedicated adapter such as `wlan0` | Supported |
| One USB Ethernet adapter for the router WAN | Supported |
| iPhone USB tethering through `ipheth` | Experimental |
| Android RNDIS, CDC Ethernet and CDC NCM tethering | Experimental |
| Ethernet-style USB cellular dongles with DHCP | Experimental |
| USB-preferred Wi-Fi fallback | Supported with iPhone or generic USB |

### Unsupported hardware

| Hardware or topology | Reason |
|---|---|
| Home Assistant Core or Container without the HAOS app | The gateway requires HAOS host networking and Supervisor |
| A downstream adapter connected to a normal LAN or switch network | The app serves authoritative DHCP on that interface |
| QMI or MBIM modems that require modem setup | The first generic USB transport supports devices that already expose an Ethernet DHCP interface |
| Multiple router-facing USB adapters without a MAC override | The app will not guess which adapter to use |

### Limitations

- iPhone USB requires **Allow Others to Join** under Personal Hotspot, an
  unlocked phone and accepted trust;
- generic USB requires exactly one supported RNDIS/CDC upstream after excluding
  management and the router-facing adapter;
- automatic failover reacts to source readiness, not Internet health;
- only IPv4 gateway service is supported;
- the entities require the Home Assistant MQTT integration and a broker;
- physical networking still needs to be commissioned for each HAOS host.

### Diagnostics

The add-on serves `GET /v2/status` and `/health` on the Supervisor-side API for
manual diagnostics. Responses redact credentials, public addresses, host
addressing, interface names and iPhone identifiers.

### Troubleshooting

| Problem | Check |
|---|---|
| The gateway remains inactive while the add-on runs | Review **Gateway state** and **Health** |
| USB is not selected | Unlock the iPhone, enable **Allow Others to Join** under Personal Hotspot, accept Trust, check `ipheth`, and confirm no other `ipheth` profile is configured in HAOS |
| Wi-Fi fallback is unavailable | Confirm the selected adapter is dedicated, its radio is on and NetworkManager-managed, the hotspot is in range, and the app credentials are correct |
| The router receives no WAN lease | Confirm the router-facing USB adapter has HAOS IPv4 and IPv6 disabled |
| More than one USB Ethernet adapter is attached | Set the optional router adapter MAC address |
| Home Assistant becomes unreachable | Stop the add-on and verify the management Ethernet remains the only main default route |
| The entities do not appear | Confirm the MQTT integration and broker are running, then restart the add-on |

## Pre-1.0 live acceptance

Pre-1.0 deployments are candidates until USB, Wi-Fi, failover, stability,
upgrade and cleanup pass end to end. MQTT entities or a router DHCP lease alone
do not prove success. Use the full
[live acceptance checklist](ha_cellular_gateway/DOCS.md#pre-10-live-acceptance)
and leave failed candidates stopped.

## Safety and security

The app uses `host_network`, `host_dbus`, `NET_ADMIN`, `NET_RAW`, Supervisor
manager access and USB access because it manages real HAOS interfaces, policy
routing, firewall rules, DHCP and optional iPhone pairing. Host D-Bus lets
`nmcli` manage only the app's temporary NetworkManager profiles. It does not
use `full_access` or `udev`.

An enforced AppArmor profile limits access to the required networking tools,
the NetworkManager D-Bus service, USB paths, sysfs entries and app-owned
runtime data. The local API uses a generated bearer token and binds to the
Supervisor-side host address.

## Development

The validation workflow runs the add-on unit tests, Python compilation, an
`import app.main` smoke check, metadata validation, AppArmor parsing and an
`aarch64` image build. See
[`.github/workflows/validate.yml`](.github/workflows/validate.yml) for the
authoritative commands.

The on-demand [NetworkManager integration
lab](ha_cellular_gateway/integration/networkmanager/README.md) runs only by
manual workflow dispatch or its local rootful Docker command. It is separate
from unit discovery and does not replace HAOS hardware acceptance.

The manual-only [QEMU Wi-Fi integration
lab](ha_cellular_gateway/integration/networkmanager_wifi/README.md) boots a
disposable KVM guest and validates real hwsim WPA plus QEMU CDC generic USB.
It runs locally on a KVM host or through its `workflow_dispatch` workflow.

The primary local checks are:

```sh
PYTHONPATH=ha_cellular_gateway \
  python -m unittest discover -s ha_cellular_gateway/tests -v

PYTHONPATH=ha_cellular_gateway \
  python -m py_compile ha_cellular_gateway/rootfs/app/*.py

PYTHONPATH=ha_cellular_gateway/rootfs python -c "import app.main"
```
