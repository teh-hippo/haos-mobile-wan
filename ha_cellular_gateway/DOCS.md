# HAOS Mobile WAN

HAOS Mobile WAN lets Home Assistant OS provide a mobile fallback connection to
a router WAN port.

```text
Phone -> Home Assistant OS -> USB Ethernet -> Router WAN
```

The Home Assistant management Ethernet remains unchanged and stays the only
main default route. Mobile traffic uses an isolated policy table and cannot
fall back through the management network.

## Before you start

1. Take a Home Assistant backup.
2. Leave the router WAN cable disconnected from the HAOS USB Ethernet adapter.
3. Keep the app on manual boot.
4. Keep the add-on stopped until you are ready to commission it.
5. Do not connect the router-facing adapter to a normal LAN port. The app
   serves DHCP on that interface while it runs.

Manual boot means the app does not start automatically after an HAOS reboot.
Enable start-on-boot only after the complete gateway path has been tested.

Do not create, edit or delete HAOS network profiles. The app detects the
management connection, owns only its temporary mobile profiles and the
router-facing address, and fails closed if the host network is unsafe.

## Choose the mobile connection

### Wi-Fi hotspot

HAOS connects to the phone over Wi-Fi.

Provide a Wi-Fi adapter dedicated to Mobile WAN. It must not be the
management interface. Enter the hotspot name and password in the app options.

The default Wi-Fi settings are:

| Setting | Default |
|---|---|
| Interface | `wlan0` |
| HAOS address | `172.20.10.4/28` |
| Phone gateway | `172.20.10.1` |
| IPv6 | Disabled |

The app creates its fixed-fingerprint Wi-Fi profile only while it runs.
NetworkManager places its connected and default routes in isolated table 203;
the app copies the selected path into policy table 201. The profile is brought
down and deleted when the add-on stops.

While running, the app temporarily reserves the selected dedicated adapter. It
turns off device autoconnect and disconnects any active connection so its own
profile controls the radio, without changing any other NetworkManager profile.
Existing Wi-Fi profiles keep their definitions unchanged. When the add-on stops,
the app restores the adapter's prior runtime state, so those profiles reconnect
as before. Legacy `Supervisor <interface>` profiles that this app created in an
earlier version are removed automatically. Raw 802.11 association status codes
remain available in the host Wi-Fi supplicant logs.

### USB (iPhone)

The app:

- starts `usbmuxd` inside the container;
- keeps pairing records in `/data/lockdown`;
- lets host NetworkManager discover and bind the dynamic `ipheth` interface;
- consumes the NetworkManager DHCP lease on that interface;
- keeps the phone default route in NetworkManager table 202, out of the main
  table.

While running, the app creates a temporary profile named
`haos-mobile-wan-iphone`, matched to the `ipheth` driver rather than an
interface name or MAC address. Autoconnect is disabled; the app activates the
profile only after the phone, trust, interface and carrier are ready.
NetworkManager owns the lease and table-202 routes. The profile is removed when
the add-on stops.

Connect the unlocked iPhone with a data-capable cable, enable **Personal
Hotspot** and **Allow Others to Join**, then accept **Trust** if prompted.
[Apple requires this toggle](https://support.apple.com/en-au/111785) for USB
tethering as well as Wi-Fi tethering.

Do not create your own `ipheth` profile in HAOS. If a different profile owns the
interface, a phone default reaches the main table, a policy rule selects table
202 or the lease is invalid, the app reports the fault and blocks fallback
rather than racing NetworkManager.

iPhone USB remains experimental because it depends on the HAOS kernel,
`ipheth`, the cable and the phone trust workflow.

### USB (generic)

Generic USB supports devices that already expose a DHCP Ethernet interface
through `rndis_host`, `cdc_ether` or `cdc_ncm`. This includes common Android
USB tethering and Ethernet-style cellular dongles.

The app excludes the HAOS management interface and the selected router-facing
adapter, then requires exactly one eligible generic USB upstream. It creates a
temporary `haos-mobile-wan-generic-usb` profile, obtains the NetworkManager
lease in table 202 and applies the same lease validation, routing and cleanup
used by iPhone USB.

Do not create a separate HAOS profile for the tether interface. An ambiguous
device set or a foreign profile that can control the selected interface blocks
the gateway rather than guessing.

QMI and MBIM devices that require modem setup are outside this first generic
USB transport. The device must already present an Ethernet-style DHCP
interface.

USB modes without Wi-Fi fallback do not claim or use Wi-Fi. When changing from
a Wi-Fi mode, the app releases its profile and restores the adapter's prior
runtime state. It does not turn off the HAOS Wi-Fi radio or modify unrelated
profiles.

### USB (iPhone), Wi-Fi fallback

This strategy keeps both app-owned profiles active while the add-on runs.

- USB is selected while the iPhone is paired, `ipheth` is available and the
  NetworkManager lease is valid.
- Wi-Fi is selected when USB is not ready.
- USB is selected again as soon as it recovers.
- The management Ethernet is never considered as a fallback.

The app removes forwarding before changing routes and NAT, so source
transitions remain fail closed.

**USB (generic), Wi-Fi fallback** uses the same selection rules with the
generic USB transport in place of the Apple pairing path.

Internet health checks remain diagnostic. They do not trigger source changes
in this release.

## App options

Starting the add-on activates the gateway; stopping it releases all gateway
state. There is no separate enable switch.

### Normal options

| Option | Purpose |
|---|---|
| **Mobile connection** | Selects Wi-Fi, iPhone USB, generic USB, or either USB transport with Wi-Fi fallback |
| **Wi-Fi hotspot name** | Required hotspot name when Wi-Fi is selected |
| **Wi-Fi hotspot password** | Required hotspot password when Wi-Fi is selected |

The Wi-Fi name and password must both be set whenever the selected strategy
uses Wi-Fi.

### Optional advanced options

| Option | Default | Use |
|---|---|---|
| Auto-disable after disconnect | `30` minutes | Stop the add-on after this long without an active gateway; use `0` to keep it running |
| Router adapter MAC address | Automatic | Select between multiple USB Ethernet adapters |
| Router WAN address | `192.168.80.1/24` | Avoid a subnet overlap |
| Wi-Fi interface | `wlan0` | Override the hotspot interface |
| Wi-Fi address | `172.20.10.4/28` | Override the HAOS hotspot address |
| Wi-Fi gateway | `172.20.10.1` | Override the phone address |

Options are read when the app starts. Restart the app after changing them.
Start or stop the add-on to control the gateway. The Home Assistant entities
published over MQTT are status-only monitoring; they do not change app options
or control the gateway.

## Commission the gateway

1. Start the add-on with the router WAN cable still disconnected.
2. Review the logs and confirm **Health** is OK.
3. Resolve every host or ownership issue. The app keeps running and fails
   closed until they clear.
4. Connect the USB Ethernet adapter only to the intended router WAN
   port.
5. If using USB, connect and trust the iPhone. If using Wi-Fi, enable the phone
   hotspot.
6. Confirm **Gateway state** moves through Waiting or Connecting to Connected.
7. Confirm the router receives the single WAN lease.
8. Confirm DNS and HTTPS traffic use the selected mobile connection.
9. Confirm Home Assistant remains reachable through management Ethernet.
10. Confirm router traffic cannot use the management interface.

While waiting or failing closed, the app removes its USB and Wi-Fi
NetworkManager profiles, router-facing address, router DHCP, forwarding, NAT and
policy routing. It retains only the downstream host-protection guard.

Stopping the add-on removes all gateway service, including the host protection
rule.

## Failure and recovery

If the mobile connection, USB Ethernet adapter, addressing, firewall backend or
policy ownership becomes unsafe, the app:

- stops router DHCP;
- removes its forwarding and NAT rules;
- removes only the policy rules and routes it owns;
- removes the exact router-facing address it added;
- retains the host protection rule while the app remains running;
- keeps running and retries every five seconds.

On graceful stop, cleanup also removes the host protection rule, deletes exact
app-owned NetworkManager profiles and stops the app `usbmuxd` helper.
`/data/state.json` records profile fingerprints and exact network ownership so
the next start can complete interrupted cleanup before reconciliation.

If the app is terminated ungracefully (a forced kill or container removal),
in-process cleanup cannot run, so a transient router-facing address and tagged
host rules can remain until the app next starts, when startup cleanup removes
the state recorded in `/data/state.json`, or until HAOS reboots. Stop the
add-on before uninstalling so cleanup completes.

Restarting the add-on is the repair path after an interrupted shutdown.
Startup cleanup runs before new gateway state is applied and logs whether
interrupted ownership was recovered. To repair the host while leaving the
add-on stopped, start it, wait for the first reconciliation, then stop it
cleanly.

The router can retain its five-minute DHCP lease after gateway service stops,
but the lease has no usable gateway during that time.

To recover:

1. Keep Home Assistant connected through management Ethernet.
2. Stop the add-on.
3. Disconnect the router WAN cable.
4. Correct the hardware or app option reported by **Health**.
5. Restart the app and repeat commissioning.

Before uninstalling, stop the add-on and let cleanup finish. The app restores
the prior adapter runtime state. If cleanup does not restore the stopped
baseline, collect diagnostics and report the defect instead of editing HAOS
networking manually.

## Home Assistant entities (MQTT)

The add-on publishes its own device and entities over MQTT discovery. It needs
the Home Assistant MQTT integration and an MQTT broker, such as the Mosquitto
broker add-on. Enable both before starting the add-on.

The **HAOS Mobile WAN** device and its entities then appear automatically. The
add-on refreshes their state while it runs, so no reload is needed after an
add-on update. The MQTT entities are status-only for monitoring. Start and stop
the app through **Settings > Apps**, or use Home Assistant's standard
`hassio.addon_start` and `hassio.addon_stop` dashboard actions. The entities
include **Gateway state**, **Connection
method**, **Connected via**, **USB status**, **Internet available**,
**Health**, interface and diagnostic sensors. Statuses read in plain language:
**Public IP** and **Connected via** show "Not connected" when no path is active,
and the downstream interface shows "Not present" when no adapter is bound.

Normal source absence reads "Waiting for iPhone", "Waiting for hotspot" or
"Waiting", depending on the configured method. **Health** remains "OK"
during normal waiting and changes to "Attention needed" only for actionable
issues, which are included in its attributes.

When the app is stopped, its MQTT entities are unavailable by design. A
dashboard can hide the running status card in that state and show a standard
button action that starts the app.

For iPhone USB mode, **USB status** reads "Waiting for Personal Hotspot" when
the phone is trusted and attached but has not presented USB tethering carrier.
Generic USB reports device, carrier, profile and lease readiness through the
same status entity.

Add the entities to a dashboard with any built-in card, for example an
`entities` card:

```yaml
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
```

Fresh installs normally create the USB entity as
`sensor.haos_mobile_wan_usb_status`. Existing installs retain their registered
entity ID, commonly `sensor.haos_mobile_wan_usb_pairing`; select the entity from
the HAOS Mobile WAN device page if the example ID differs.

The add-on still serves `GET /v2/status` and `/health` on the Supervisor-side
API for manual diagnostics.

## Live acceptance

A deployment remains a candidate until every applicable live gate passes.
Keep the app stopped before, between and after scenarios.

1. **Upgrade and baseline:** verify automatic legacy-lineage cleanup, that any
   genuine foreign Wi-Fi profile is preserved unchanged, no active app profiles,
   no gateway data plane, the downstream host guard, and an unchanged
   management default route.
2. **iPhone USB:** require trust, `ipheth` carrier, the app profile,
   NetworkManager lease/table 202, Connected, OK, Internet available,
   public IP, router WAN lease and LAN DNS/HTTPS.
3. **USB stability:** sustain the path, then lock/unlock the phone, toggle
   Personal Hotspot and reconnect the cable. Recovery must not require an app
   restart.
4. **Generic USB:** require the expected RNDIS/CDC driver, app profile,
   NetworkManager lease/table 202, Connected, OK, Internet available and
   exact cleanup. Verify the router-facing adapter is never selected upstream.
5. **Wi-Fi:** require the dedicated app profile, table 203, Connected, OK,
   Internet available, router WAN lease and LAN HTTPS. Stop the add-on and
   confirm the profile is deleted and the adapter's prior runtime state is
   restored.
6. **Failover:** with USB-preferred fallback, remove USB and require Wi-Fi;
   restore USB and require a clean return without stale routing or NAT.
7. **Cleanup:** verify stop, auto-stop, restart while Connected/Waiting,
   interrupted-stop recovery and exact journal cleanup.

For each gate record timestamps, Gateway state, Health issues, profile UUID and
state, carrier, address, selected source, route tables, router lease, LAN
traffic and final cleanup.

Stop immediately if the management route changes, a foreign profile is
modified, table 201 selects an unverified source, the router receives a lease
without proven upstream Internet, or cleanup cannot restore the stopped
baseline.

The `networkmanager` object in `/v2/status` reports the secret-safe ownership
phase, the Wi-Fi custody phase and restoration-pending state, app profile UUIDs
and profile states. `upstream_carrier` reports the latest iPhone carrier
observation. These fields contain no passwords.
The `networkmanager` object is exposed as an attribute on **Health**, while
`upstream_carrier` and the carrier fallback fields are attributes on **Gateway
state**, for acceptance evidence through Home Assistant.

## Security

The app uses `host_network`, `host_dbus`, `NET_ADMIN`, `NET_RAW`, `hassio_api`,
`hassio_role: manager` and `usb: true`.

- Host networking and `NET_ADMIN` are required for real HAOS interfaces,
  policy routing and tagged firewall rules.
- `NET_RAW` is required by the DHCP services.
- Supervisor access is required for MQTT service details and the auto-stop
  self-stop request to Supervisor.
- Host D-Bus is required so `nmcli` can manage the app-owned iPhone USB and
  Wi-Fi profiles, and so the app can read and write the Wi-Fi profile's
  recovery marker directly over the NetworkManager `Settings.Connection` API.
  The AppArmor profile scopes D-Bus to NetworkManager.
- USB access is required by the iPhone path and is static for the app package.
  Generic USB uses the host network interface after its kernel driver binds.

The app does not use `full_access` or `udev`.

The enforced AppArmor profile limits the process to its networking tools,
app-owned data, required `/proc` and sysfs reads, and the USB runtime paths.
The API binds to the Supervisor-side address and requires a generated bearer
token. Diagnostics redact credentials, addressing, interface names and iPhone
identifiers.

Generic USB remains experimental until physical Android/RNDIS or CDC hardware
passes the complete live acceptance sequence.
