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
4. Keep **Enabled** off.
5. Do not connect the router-facing adapter to a normal LAN port. The app
   serves DHCP on that interface when enabled.

Manual boot means the app does not start automatically after an HAOS reboot.
Enable start-on-boot only after the complete gateway path has been tested.

## Prepare HAOS networking

The app detects the management interface and its current IPv4 address. It does
not change that interface or its NetworkManager profile.

Use the Terminal & SSH app or another supported HAOS console.

### Inspect the interfaces

```sh
ha --raw-json network info
ha network info end0
ha network info wlan0
```

Attach the USB Ethernet adapter that will connect to the router WAN, then run
the network command again. The app selects the only eligible USB Ethernet
adapter automatically.

If more than one eligible adapter is attached, set the optional **Router
adapter MAC address**.

### Keep the management connection unchanged

Confirm that the management Ethernet:

- has one unambiguous IPv4 address;
- remains reachable;
- is the only interface with a main default route.

The app detects this baseline at startup and disables gateway service if it
changes unexpectedly.

### Prepare the router-facing adapter

Replace `enp1s0u1` with the detected USB Ethernet interface:

```sh
ha network update enp1s0u1 \
  --ipv4-method disabled \
  --ipv6-method disabled
```

Do not configure an address, gateway or DNS server on this interface. When
enabled, the app owns one exact address and removes it during disable, failure
or shutdown.

The default router WAN transit address is `192.168.80.1/24`. The app leases
`192.168.80.2` to the router and advertises `.1` as its gateway.

This subnet is not detected from the phone or router. It is a private default
that must not overlap the Home Assistant management network, the phone network
or the router LAN. If it does, set the optional **Router WAN address**.

## Choose the mobile connection

### Wi-Fi hotspot

HAOS connects to the phone over Wi-Fi.

Leave the Wi-Fi hotspot name and password empty to keep an existing HAOS Wi-Fi
profile. Set both values to let the app apply the profile through Supervisor
when it starts.

The default Wi-Fi settings are:

| Setting | Default |
|---|---|
| Interface | `wlan0` |
| HAOS address | `172.20.10.4/28` |
| Phone gateway | `172.20.10.1` |
| IPv6 | Disabled |

The app intentionally omits a Wi-Fi main-table gateway. It installs the phone
gateway only in its own routing table.

To configure the profile outside the app:

```sh
ha network update wlan0 \
  --wifi-mode infrastructure \
  --wifi-auth wpa-psk \
  --wifi-ssid "MobileHotspot" \
  --wifi-psk "REPLACE_WITH_HOTSPOT_PASSWORD" \
  --ipv4-method static \
  --ipv4-address 172.20.10.4/28 \
  --ipv4-nameserver 1.1.1.1 \
  --ipv4-nameserver 8.8.8.8 \
  --ipv6-method disabled
```

Do not add an IPv4 gateway to this HAOS profile.

### USB (iPhone)

The app:

- starts `usbmuxd` inside the container;
- keeps pairing records in `/data/lockdown`;
- lets host NetworkManager discover and bind the dynamic `ipheth` interface;
- consumes the NetworkManager DHCP lease on that interface;
- keeps the phone default route in NetworkManager table 202, out of the main
  table.

Host NetworkManager owns the iPhone connection through a persistent profile
named `haos-mobile-wan-iphone`. The app creates that profile through `nmcli`
before a phone is inserted, matches it to the `ipheth` driver rather than an
interface name or MAC address, and reconciles it only when it is missing or has
drifted. NetworkManager owns the address, renewals and DHCP-derived routes; the
app does not edit its leased address or table 202 routes.

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

### USB (iPhone), Wi-Fi fallback

This strategy prepares both mobile paths.

- USB is selected while the iPhone is paired, `ipheth` is available and the
  NetworkManager lease is valid.
- Wi-Fi is selected when USB is not ready.
- USB is selected again as soon as it recovers.
- The management Ethernet is never considered as a fallback.

The app removes forwarding before changing routes and NAT, so source
transitions remain fail closed.

Internet health checks remain diagnostic. They do not trigger source changes
in this release.

## App options

### Normal options

| Option | Purpose |
|---|---|
| **Enabled** | Starts or stops gateway service to the router |
| **Mobile connection** | Selects Wi-Fi, USB (iPhone), or USB-preferred Wi-Fi fallback |
| **Wi-Fi hotspot name** | Optional app-managed Wi-Fi name |
| **Wi-Fi hotspot password** | Optional app-managed Wi-Fi password |

The Wi-Fi name and password must both be set or both be empty.

### Optional advanced options

| Option | Default | Use |
|---|---|---|
| Router adapter MAC address | Automatic | Select between multiple USB Ethernet adapters |
| Router WAN address | `192.168.80.1/24` | Avoid a subnet overlap |
| Wi-Fi interface | `wlan0` | Override the hotspot interface |
| Wi-Fi address | `172.20.10.4/28` | Override the HAOS hotspot address |
| Wi-Fi gateway | `172.20.10.1` | Override the phone address |

Options are read when the app starts. Restart the app after changing them.
The app option controls startup state. The optional integration switch controls
the current app process and does not rewrite saved app options.

## Upgrade to 0.4.0

Version 0.4.0 is a breaking app and integration update. The old option names,
mode API and select entities are not retained.

1. Disable the 0.3 gateway and let cleanup finish.
2. Update the HAOS app.
3. Select the required **Mobile connection** again.
4. Re-enter **Router WAN address** only if the default
   `192.168.80.1/24` is unsuitable.
5. Confirm the Wi-Fi hotspot fields, then restart the app.
6. Update the HACS integration to 0.4.0.
7. Restart Home Assistant.
8. Remove any unavailable legacy Mode select or Mode sensors from the entity
   registry.
9. Repeat the disabled commissioning checks before enabling the gateway.

The app and integration use API v2. The integration is expected to be
unavailable while only one side of the breaking update has been installed.

## Commission the gateway

1. Start the app with **Enabled** off.
2. Review the logs, **Safety checks**, **USB pairing** and **Last error**.
3. Resolve every host or ownership error.
4. If using USB, connect and trust the iPhone.
5. Confirm the selected mobile connection is ready while the gateway remains
   disabled.
6. Connect the prepared USB Ethernet adapter only to the intended router WAN
   port.
7. Turn **Enabled** on.
8. Confirm the router receives the single WAN lease.
9. Confirm DNS and HTTPS traffic use the selected mobile connection.
10. Confirm Home Assistant remains reachable through management Ethernet.
11. Confirm router traffic cannot use the management interface.

While disabled, the app may prepare Wi-Fi, pair the iPhone, maintain the USB
lease and protect HAOS from the router-facing interface. It does not install
the router-facing address, router DHCP, forwarding, NAT or policy routing.

Turning **Enabled** off removes gateway service while keeping the host
protection rule until the app stops.

## Failure and recovery

If the mobile connection, USB Ethernet adapter, addressing, firewall backend or
policy ownership becomes unsafe, the app:

- stops router DHCP;
- removes its forwarding and NAT rules;
- removes only the policy rules and routes it owns;
- removes the exact router-facing address it added;
- retains the host protection rule while the app remains running;
- keeps the enabled request and retries every five seconds.

On graceful stop, cleanup also removes the host protection rule and stops the
app `usbmuxd` helper. It leaves the persistent NetworkManager profile, its
address and its table 202 routes in place. `/data/state.json` records exact
ownership so the next start can clean interrupted state before reconciliation.

The router can retain its five-minute DHCP lease after gateway service stops,
but the lease has no usable gateway during that time.

To recover manually:

1. Keep Home Assistant connected through management Ethernet.
2. Turn **Enabled** off or stop the app.
3. Disconnect the router WAN cable.
4. Correct the HAOS interface profile or app options.
5. Restart the app and repeat commissioning.

Before uninstalling, turn **Enabled** off and let cleanup finish. Restore the
USB Ethernet profile if the adapter will return to ordinary networking:

```sh
ha network update enp1s0u1 \
  --ipv4-method auto \
  --ipv6-method auto
```

## Optional Home Assistant integration

The optional HACS integration adds:

- an **Enabled** switch;
- mobile and active connection sensors;
- iPhone USB pairing status;
- safety, DHCP, rule and interface sensors;
- Repairs and redacted diagnostics;
- an immediate reconciliation button.

The integration polls the app every 30 seconds. It is separate from the app and
requires a Home Assistant restart after installation or update.

## Security

The app uses `host_network`, `host_dbus`, `NET_ADMIN`, `NET_RAW`, `hassio_api`,
`hassio_role: manager` and `usb: true`.

- Host networking and `NET_ADMIN` are required for real HAOS interfaces,
  policy routing and tagged firewall rules.
- `NET_RAW` is required by the DHCP services.
- Supervisor manager access is required to apply app-managed Wi-Fi profiles.
- Host D-Bus is required so `nmcli` can drive the host NetworkManager iPhone USB
  profile. The AppArmor profile scopes D-Bus to the NetworkManager service.
- USB access is required by the iPhone path and is static for the app package.

The app does not use `full_access` or `udev`.

The enforced AppArmor profile limits the process to its networking tools,
app-owned data, required `/proc` and sysfs reads, and the iPhone USB paths.
The API binds to the Supervisor-side address and requires a generated bearer
token. Diagnostics redact credentials, addressing, interface names and iPhone
identifiers.

Generic Android, RNDIS and CDC USB tethering is not yet supported. It is
tracked in [issue #96](https://github.com/teh-hippo/haos-mobile-wan/issues/96).
