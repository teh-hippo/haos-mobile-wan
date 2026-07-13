# HAOS Mobile WAN

HAOS Mobile WAN turns a Home Assistant OS host into an isolated mobile WAN
gateway. It does not know about or control the downstream router. The router
only needs a WAN Ethernet port configured as a DHCP client.

## Network roles

| Interface | Role |
|---|---|
| Management Ethernet, usually `end0` | Normal Home Assistant LAN and main default route |
| Wi-Fi, usually `wlan0` | Phone hotspot upstream |
| USB Ethernet | Isolated downstream connection to a router WAN port |

The app:

- serves DHCP only on the USB Ethernet interface;
- routes that transit subnet through a dedicated policy table;
- permits forwarding only between the USB Ethernet interface and Wi-Fi;
- masquerades only the configured transit subnet;
- blocks IPv6 on the fallback path;
- protects HAOS host-local services from the downstream interface;
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

The app deliberately validates persistent host networking but does not modify
it. This avoids an app error replacing or disconnecting Home Assistant's
management network.

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

Do not change the management interface. Record its current static address and
confirm it owns the main default route.

### 3. Configure the phone hotspot interface

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

### 4. Configure the USB Ethernet interface

Replace `enx001122334455` with the detected interface:

```sh
ha network update enx001122334455 \
  --ipv4-method static \
  --ipv4-address 192.168.80.1/24 \
  --ipv6-method disabled
```

Do not configure a gateway or DNS servers on this interface.

### 5. Verify the host baseline

Confirm:

- management remains reachable;
- the management interface is the only main default route;
- `wlan0` has the expected static address and no main default route;
- the USB interface has the expected downstream address;
- IPv6 is disabled on Wi-Fi and USB Ethernet;
- the app options contain the USB adapter's MAC;
- the three configured IPv4 networks do not overlap.

## App options

The defaults are examples and must match the target host.

| Option | Purpose |
|---|---|
| `management_interface`, `management_address` | Baseline that must remain unchanged |
| `upstream_interface`, `upstream_address`, `upstream_gateway` | Phone hotspot path |
| `downstream_mac`, `downstream_address` | Stable USB adapter identity and gateway |
| `transit_subnet`, `dhcp_start`, `dhcp_end` | Isolated router WAN network |
| `dns_servers` | Public DNS servers advertised by DHCP |
| `trial_seconds` | Automatic trial rollback period |

`routing_table`, `reconcile_seconds`, `api_bind` and `api_port` are advanced
compatibility settings. Leave them unchanged unless resolving a measured
conflict.

Options are read when the app starts. Restart the app after changing them.

## Commissioning

1. Start the app with disabled mode and dry-run enabled.
2. Review the logs and safety-check status. Resolve every reported error.
3. Set `dry_run: false`, keep `mode: disabled`, save and restart.
4. Connect the USB Ethernet cable only to the intended router WAN port.
5. Select `trial` mode.
6. Confirm the router receives an address from the configured DHCP range.
7. Confirm DNS and HTTPS traffic use the phone hotspot.
8. Confirm Home Assistant management remains reachable.
9. Confirm no transit traffic can use the management interface.

Trial mode automatically tears down DHCP, firewall, NAT and policy routing
after `trial_seconds`. The absolute deadline is stored under `/data`, so an app
restart does not grant additional trial time.

After a successful trial, set `mode: active` in the app options and restart.
Enable start-on-boot only after reboot recovery has also been tested.

## Failure and recovery behaviour

If Wi-Fi, the USB adapter, addressing, firewall backend or policy ownership
becomes unsafe, the app:

- stops DHCP;
- removes its tagged forwarding and NAT rules;
- removes only the exact policy rules and routes it owns;
- keeps the requested active mode so it can recover automatically when every
  safety check passes again.

The app never flushes host firewall base chains or deletes policy rules by
priority alone.

To recover:

1. Keep Home Assistant connected through the management interface.
2. Stop the app from the Apps panel.
3. Disconnect the USB Ethernet cable from the downstream router.
4. Correct HAOS interface configuration or app options.
5. Restart in disabled dry-run mode.

## Optional Home Assistant integration

The app is fully operable without the custom integration. The optional
`ha_cellular_gateway` integration adds status entities and runtime controls.
Adding this Apps repository does not install the integration.

## Security status

The app uses only `NET_ADMIN` and `NET_RAW`, without `full_access` or host
D-Bus. Its AppArmor profile remains in complain mode while the network command
surface is audited on real hardware. AppArmor currently records policy misses
but does not enforce them. Runtime isolation therefore depends on the app's
scoped netfilter and policy-routing rules.

The API binds to the Supervisor-side host address and requires a generated
Bearer token. Diagnostics redact credentials, public addressing and network
topology.
