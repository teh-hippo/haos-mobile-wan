# HAOS Mobile WAN

HAOS Mobile WAN turns a Home Assistant OS host into an isolated mobile WAN
gateway. It does not know about or control the downstream router. The router
only needs a WAN Ethernet port configured as a DHCP client.

## Network roles

| Interface | Role |
|---|---|
| Management Ethernet, usually `end0` | Normal Home Assistant LAN and main default route |
| Wi-Fi, usually `wlan0` | Default phone hotspot upstream |
| `ipheth`, dynamic name such as `eth0` | Optional experimental iPhone USB-tethering upstream |
| USB Ethernet | Isolated downstream connection to a router WAN port |

The app:

- serves DHCP only on the USB Ethernet interface;
- routes that transit subnet through a dedicated policy table;
- permits forwarding only between the USB Ethernet interface and Wi-Fi;
- masquerades only the configured transit subnet;
- blocks IPv6 on the fallback path;
- protects HAOS host-local services from the downstream interface;
- keeps iPhone USB DHCP off the main routing table;
- fails closed instead of falling back through the management LAN.

## Safety first

Before commissioning:

1. Take a full Home Assistant backup.
2. Leave the USB adapter's RJ45 cable disconnected.
3. Keep the app on manual boot.
4. Keep `mode: disabled`.
5. Keep `dry_run: true`.
6. Do not connect the downstream adapter to a normal LAN port. It runs an
   authoritative DHCP server when enabled.

Manual boot means the app does not restart automatically after HAOS reboots.
Enable start-on-boot in the Apps panel only after a successful hardware trial.

## Configure HAOS networking

The app discovers and validates the management network but never changes it.
The USB Ethernet profile must be left without host-managed IP addressing. The
app then owns one exact runtime address on that interface and can remove it
cleanly during rollback or shutdown.

Use the Terminal & SSH app or another supported HAOS console.

### 1. Inspect interfaces

```sh
ha --raw-json network info
ha network info end0
ha network info wlan0
```

After attaching the USB Ethernet adapter, run `ha --raw-json network info`
again. Record its interface name and MAC address.

### 2. Preserve management Ethernet

Do not change the management interface. Confirm it has one unambiguous IPv4
address and is the only interface with a main default route. The app detects
both values at startup.

### 3. Choose the upstream mode

`upstream_mode: hotspot_wifi` is the default and keeps the current static Wi-Fi
commissioning flow.

`upstream_mode: iphone_usb` is experimental. The app:

- requires the app's `usb: true` permission;
- starts `usbmuxd` inside the container;
- persists `/var/lib/lockdown` under `/data/lockdown`;
- pairs only after you unlock the iPhone and tap **Trust**;
- owns DHCP on the detected `ipheth` interface itself.

If pairing, `ipheth` or DHCP never become ready, the app stays disabled and
reports a focused preflight error instead of guessing.

### 3a. Keep `ipheth` app-owned

Do not configure the dynamic `ipheth` interface in HAOS. Leave IPv4, DHCP and
the main default route unmanaged on that interface so the app can own them.

If `ipheth` already has a host-managed IPv4 address or main default route, the
app reports an ownership conflict and stays disabled instead of racing HAOS or
NetworkManager for DHCP.

### 4. Configure the phone hotspot interface

The example defaults match an iPhone Personal Hotspot:

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

Do not configure an IPv4 gateway on `wlan0`. The app adds the phone gateway
only to its dedicated policy table. Verify that `wlan0` does not appear as a
main-table default route.

### 5. Configure the USB Ethernet interface

Replace `enp1s0u1` with the detected interface:

```sh
ha network update enp1s0u1 \
  --ipv4-method disabled \
  --ipv6-method disabled
```

Do not configure an address, gateway or DNS servers on this interface. The app
rejects host-managed IPv4 addresses, installs its configured downstream address
only during activation, and deletes that exact address when it rolls back.

With one eligible USB Ethernet adapter attached, the app selects it
automatically. If more than one is attached, set `downstream_mac` to the
intended adapter's MAC address.

### 6. Verify the host baseline

Confirm:

- management remains reachable;
- the management interface is the only main default route;
- `wlan0` has the expected static address and no main default route;
- the USB interface has no host-managed IPv4 address;
- IPv6 is disabled on Wi-Fi and USB Ethernet;
- the three configured IPv4 networks do not overlap.

## App options

The defaults are examples and must match the target host.

| Normal option | Purpose |
|---|---|
| `mode` | `disabled`, time-limited `trial`, or persistent `active` startup state |
| `dry_run` | Blocks every downstream mutation while preflight checks run |
| `upstream_mode` | `hotspot_wifi` for the existing Wi-Fi path, `iphone_usb` for experimental USB tethering |
| `downstream_address` | Private gateway address and subnet used only for the router WAN transit |

The optional `downstream_mac`, `upstream_interface`, `upstream_address` and
`upstream_gateway` fields are hidden with the unused optional settings. The MAC
selects between multiple USB Ethernet adapters. The hotspot fields override the
standard `wlan0`, `172.20.10.4/28` and `172.20.10.1` defaults.

The transit subnet is derived from `downstream_address`. The app offers one
five-minute DHCP lease to the router, uses public IPv4 resolvers, policy table
201, a five-second reconciliation interval, a five-minute trial, and the fixed
Supervisor-local API endpoint. These are implementation details rather than
user settings.

Options are read when the app starts. Restart the app after changing them.

## Commissioning

1. Start the app with disabled mode and dry-run enabled.
2. Review the logs and safety-check status. Resolve every reported error.
3. Set `dry_run: false`, keep `mode: disabled`, save and restart.
   This permits iPhone USB pairing when selected and installs only the
   downstream host-ingress guard. The downstream address, forwarding, DHCP and
   policy routing remain absent.
4. If using `iphone_usb`, connect the iPhone by USB, unlock it, enable Personal
   Hotspot and tap **Trust** when prompted. Then press **Reapply gateway state**
   until the pairing state becomes `paired`.
5. Confirm the selected upstream is ready while the gateway still remains
   disabled.
6. Connect the USB Ethernet cable only to the intended router WAN port.
7. Select `trial` mode.
8. Confirm the router receives an address from the configured DHCP range.
9. Confirm DNS and HTTPS traffic use the selected mobile upstream.
10. Confirm Home Assistant management remains reachable.
11. Confirm no transit traffic can use the management interface.

Trial mode automatically tears down the transient downstream address, DHCP,
forwarding, NAT and policy routing after five minutes. The host-ingress guard
remains while the app is running. The absolute deadline is stored under
`/data`, so an app restart does not grant additional trial time.

After a successful trial, set `mode: active` in the app options and restart.
Enable start-on-boot only after reboot recovery has also been tested.

## Failure and recovery behaviour

If Wi-Fi, the USB adapter, addressing, firewall backend or policy ownership
becomes unsafe, the app:

- stops DHCP;
- removes its tagged forwarding and NAT rules;
- removes only the exact policy rules and routes it owns;
- removes the exact transient downstream address it added;
- retains its downstream host-ingress guard while the app is running;
- keeps the requested active mode so it can recover automatically when every
  safety check passes again.

The app never flushes host firewall base chains or deletes policy rules by
priority alone. It never changes the management NetworkManager profile or the
USB Ethernet NetworkManager profile.

On graceful stop, the same cleanup also removes the host-ingress guard before
the container exits. The Supervisor allows 30 seconds for this teardown. If the
process is killed without cleanup, `/data/state.json` records the exact owned
address, routes and rules so the next start removes them before reconciliation.
An HAOS reboot also clears transient interface and firewall state.

The downstream router can retain its last DHCP lease for up to five minutes
after the app stops. It receives no usable gateway service during that period.

To recover:

1. Keep Home Assistant connected through the management interface.
2. Stop the app from the Apps panel.
3. Disconnect the USB Ethernet cable from the downstream router.
4. Correct HAOS interface configuration or app options.
5. Restart in disabled dry-run mode.

Before uninstalling, return to disabled mode and let the app complete one
reconcile or stop cleanly. If the USB adapter will be reused for ordinary
networking, restore its HAOS profile afterwards, for example:

```sh
ha network update enp1s0u1 \
  --ipv4-method auto \
  --ipv6-method auto
```

## iPhone USB feasibility and limits

This path is intentionally experimental on stock HAOS 18.1:

- it depends on the host `ipheth` kernel driver appearing for the connected
  iPhone;
- it depends on container USB access plus `usbmuxd`/`libimobiledevice`;
- the interface name is discovered dynamically and must not be hard-coded;
- the trust workflow is still user-driven on the phone;
- real hardware validation is still required for every target HAOS build.

If the phone is visible over USB but pairing cannot complete, the app fails
closed and keeps downstream forwarding disabled.

## Optional Home Assistant integration

The app is fully operable without the custom integration. The optional
`ha_cellular_gateway` integration adds status entities and runtime controls.
Adding this Apps repository does not install the integration.

## Security status

The app uses `host_network: true`, `NET_ADMIN`, `NET_RAW`, `hassio_api: true`
and `usb: true`, without `full_access`, host D-Bus or `udev`.

- `host_network` is required because the app validates and mutates the HAOS
  host firewall, routing tables and real network interfaces.
- `NET_ADMIN` is required for the app's tagged `iptables`/`ip6tables`, route
  and policy-rule ownership model.
- `NET_RAW` remains required because `dnsmasq` and `udhcpc` own DHCP on the
  downstream and `iphone_usb` interfaces.
- `usb: true` remains required for the supported `iphone_usb` path because
  Home Assistant App permissions are static per app and cannot be toggled per
  `upstream_mode`.

That static-permission model is the supported exemption for hotspot-only
deployments: `hotspot_wifi` does not use USB at runtime, but the app still
ships with the minimal shared permission set needed for the existing iPhone USB
path. If dormant USB exposure is unacceptable on a given host, this app does
not currently offer a separate hotspot-only package.

The enforced AppArmor profile is limited to the app payload, its own `/data`
state, `/run/ha-cellgw`, the `usbmuxd` runtime socket, the required `ip`,
`iptables`, `dnsmasq`, `curl`, `usbmuxd`, `idevice*`, `udhcpc` and `/bin/sh`
executables (the shell is required by the udhcpc DHCP callback script), the
specific `/proc/sys/net/ipv4` checks, `/sys/class/net`, `/sys/devices` (sysfs
symlink traversal for ipheth network interface detection), `ipheth` USB sysfs
inspection and `/dev/bus/usb`.

The API binds to the Supervisor-side host address and requires a generated
Bearer token. Diagnostics redact credentials, public addressing and network
topology.
