# HAOS Mobile WAN

HAOS Mobile WAN provides a mobile fallback connection to a router WAN port.

```text
Phone -> Home Assistant OS -> USB Ethernet -> Router WAN
```

The Home Assistant management connection remains the only main default route.
Mobile traffic uses isolated routing tables and cannot fall back through the
management network.

## Before you start

1. Take a Home Assistant backup.
2. Leave the router WAN cable disconnected from the HAOS USB Ethernet adapter.
3. Keep the app stopped and on manual boot.
4. Do not connect the router-facing adapter to a normal LAN port. The app
   serves DHCP on that interface while running.
5. Do not create or edit HAOS network profiles for the selected mobile
   adapters.

Enable start-on-boot only after the full gateway path and cleanup have been
tested.

## Connection modes

### Wi-Fi hotspot

Use a Wi-Fi adapter dedicated to Mobile WAN. It must not be the management
interface.

The app creates a temporary profile, reserves the adapter while running and
restores its previous runtime state when stopped. Existing profile definitions
are not changed.

Defaults:

| Setting | Default |
|---|---|
| Interface | `wlan0` |
| HAOS address | `172.20.10.4/28` |
| Phone gateway | `172.20.10.1` |
| NetworkManager route table | `203` |
| IPv6 | Disabled |

### USB (iPhone)

Connect an unlocked iPhone with a data-capable cable, enable **Personal
Hotspot** and **Allow Others to Join**, then accept **Trust** if prompted.
[Apple requires this setting](https://support.apple.com/en-au/111785) for USB
tethering.

The app runs `usbmuxd`, stores pairing records under `/data/lockdown`, creates
a temporary NetworkManager profile for the dynamic `ipheth` interface and
keeps its default route in table `202`. The profile is removed when the app
stops.

Do not create a separate `ipheth` profile in HAOS. A foreign profile, invalid
lease or main-table mobile default blocks the gateway.

### USB (generic)

Generic USB supports one eligible DHCP Ethernet interface exposed by
`rndis_host`, `cdc_ether` or `cdc_ncm`. This covers common Android USB
tethering and Ethernet-style cellular dongles.

The app excludes the management and router-facing adapters, creates a
temporary NetworkManager profile and applies the same table `202` isolation,
lease validation and cleanup used by iPhone USB.

QMI and MBIM devices that require modem setup are outside this transport.

### USB-preferred Wi-Fi fallback

The iPhone and generic USB fallback modes keep the applicable USB profile and
the dedicated Wi-Fi profile ready while the app runs.

- USB is selected while its device, carrier and lease are ready.
- Wi-Fi is selected while USB is unavailable.
- USB is selected again when it recovers.
- The management connection is never a fallback.

Forwarding is removed before routes and NAT change. Internet probes are
diagnostic and do not choose the source.

## App options

Starting the app activates the gateway. Stopping it releases all owned gateway
state.

| Option | Default | Purpose |
|---|---|---|
| Mobile connection | Wi-Fi hotspot | Select Wi-Fi, USB or USB-preferred fallback |
| Wi-Fi hotspot name | Empty | Required when the selected mode uses Wi-Fi |
| Wi-Fi hotspot password | Empty | Required when the selected mode uses Wi-Fi |
| Auto-disable after disconnect | `30` minutes | Stop after this long without an active gateway; use `0` to keep running |
| Router adapter MAC address | Automatic | Select between multiple USB Ethernet adapters |
| Router WAN address | `192.168.80.1/24` | Avoid a subnet overlap |
| Wi-Fi interface | `wlan0` | Override the hotspot adapter |
| Wi-Fi address | `172.20.10.4/28` | Override the HAOS hotspot address |
| Wi-Fi gateway | `172.20.10.1` | Override the phone address |

Options are read at startup. Restart the app after changing them.

## Commission the gateway

1. Start the app with the router WAN cable disconnected.
2. Confirm **Health** is **OK** or resolve every reported issue.
3. Connect the dedicated USB Ethernet adapter only to the router WAN port.
4. Make the selected phone connection available.
5. Confirm **Gateway state** reaches **Connected**.
6. Confirm the router receives the single WAN lease.
7. Confirm DNS and HTTPS traffic use the mobile connection.
8. Confirm Home Assistant remains reachable through management Ethernet.
9. Confirm router traffic cannot use the management interface.
10. Stop the app and confirm its routes, firewall rules, DHCP service,
    addresses and temporary NetworkManager profiles are removed.

While waiting or failing closed, the app removes the gateway data plane and
retains only downstream host protection. A graceful stop removes that
protection too.

## Failure and recovery

The app records exact network and profile ownership in `/data/state.json`.
After an interrupted shutdown, the next start performs cleanup before applying
new gateway state.

To repair the host while leaving the app stopped:

1. Start the app.
2. Wait for the first reconciliation and startup cleanup.
3. Stop it cleanly.

Before uninstalling, stop the app and allow cleanup to finish. If the stopped
baseline is not restored, collect diagnostics and report the defect rather
than editing HAOS networking manually.

The router may retain its five-minute DHCP lease after the app stops, but the
lease has no usable gateway.

## Home Assistant entities

The app publishes its device through MQTT discovery. Enable the Home Assistant
MQTT integration and a broker, such as the Mosquitto broker app, before
starting Mobile WAN.

The entities report:

- gateway and health state;
- configured and active connection;
- USB readiness;
- Internet availability and public IP;
- downstream presence;
- firewall and DHCP state.

The MQTT entities remain unavailable while the app is stopped. Dashboard
controls use Home Assistant's add-on actions rather than MQTT commands.

### Dashboard example

Replace `YOUR_ADDON_SLUG` with the slug Home Assistant uses for this
installation. It is visible in the app page URL and may include a repository
prefix. Existing entity IDs can also differ after upgrades, so select them from
the **HAOS Mobile WAN** device when necessary.

```yaml
type: vertical-stack
cards:
  - type: conditional
    conditions:
      - condition: state
        entity: sensor.haos_mobile_wan_gateway_state
        state_not:
          - unavailable
          - unknown
    card:
      type: entities
      title: Mobile WAN
      icon: mdi:wan
      show_header_toggle: false
      entities:
        - entity: sensor.haos_mobile_wan_gateway_state
          name: Gateway state
        - entity: sensor.haos_mobile_wan_health
          name: Health
        - entity: sensor.haos_mobile_wan_connected_via
          name: Connected via
        - entity: binary_sensor.haos_mobile_wan_internet_available
          name: Internet available
        - entity: sensor.haos_mobile_wan_usb_status
          name: USB status
        - entity: sensor.haos_mobile_wan_public_ip
          name: Public IP
        - type: button
          name: Gateway is running
          icon: mdi:power
          action_name: Stop
          tap_action:
            action: perform-action
            perform_action: hassio.addon_stop
            data:
              addon: YOUR_ADDON_SLUG
  - type: conditional
    conditions:
      - condition: state
        entity: sensor.haos_mobile_wan_gateway_state
        state:
          - unavailable
          - unknown
    card:
      type: entities
      title: Mobile WAN
      icon: mdi:wan
      show_header_toggle: false
      entities:
        - type: button
          name: Gateway is stopped
          icon: mdi:power
          action_name: Start
          tap_action:
            action: perform-action
            perform_action: hassio.addon_start
            data:
              addon: YOUR_ADDON_SLUG
```

## Live acceptance

Keep the app stopped before, between and after test scenarios.

1. Verify the stopped baseline and unchanged management default route.
2. Test every configured source through connection, router lease, DNS and
   HTTPS.
3. Exercise cable removal, phone lock and unlock, hotspot changes and source
   recovery.
4. For fallback, remove USB, require Wi-Fi, then restore USB and require a
   clean return.
5. Test stop, auto-stop, restart while connected and waiting, and interrupted
   cleanup recovery.
6. Confirm final profile, route, firewall, address, DHCP and journal cleanup.

Stop immediately if the management route changes, a foreign profile is
modified, the router receives a lease without a verified upstream, or cleanup
cannot restore the stopped baseline.

## Diagnostics and security

The app serves `GET /v2/status` and `/health` on the Supervisor-side API.
Diagnostics and logs do not expose credentials.

Required privileges are limited to host networking, NetworkManager D-Bus,
`NET_ADMIN`, `NET_RAW`, Supervisor manager access and USB access. The app does
not use `full_access` or `udev`. Its AppArmor profile confines networking
tools, app-owned data, required `/proc` and sysfs reads, NetworkManager D-Bus
and USB runtime paths.
