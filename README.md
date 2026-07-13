# HAOS Mobile WAN

Home Assistant OS app for a redundant mobile WAN gateway.

The app is intentionally safe by default:

- manual boot;
- `mode: disabled`;
- `dry_run: true`;
- no route, firewall, NAT or DHCP mutation without passing safety checks;
- no `full_access` capability.

## Architecture

- `end0`: unchanged Home Assistant management network;
- `wlan0`: iPhone hotspot upstream, with no main-table default route;
- USB Ethernet NIC: isolated downstream to a separate UniFi WAN profile;
- policy routing table 201;
- tagged `iptables-nft` rules through Docker's `DOCKER-USER`;
- dnsmasq bound only to the downstream NIC;
- fail-closed teardown and automatic recovery after transient interface loss;
- typed authenticated local API;
- optional Supervisor-discovered Home Assistant integration.

## Repository layout

- `ha_cellular_gateway/`: Home Assistant app;
- `custom_components/ha_cellular_gateway/`: optional companion integration
  source used by the current prototype.

Adding this repository to Home Assistant installs the app only. It does not
install the optional custom integration.

## Installation

In Home Assistant:

1. Open **Settings > Apps > App store**.
2. Open the menu and select **Repositories**.
3. Add `https://github.com/teh-hippo/haos-mobile-wan`.
4. Install **HAOS Mobile WAN**.

Leave manual boot, disabled mode and dry-run enabled until every interface and
address has been configured for the target HAOS host.

## Development validation

```sh
PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=ha_cellular_gateway \
  python -m unittest discover -s ha_cellular_gateway/tests -v

PYTHONDONTWRITEBYTECODE=1 python -m py_compile \
  ha_cellular_gateway/rootfs/app/*.py \
  custom_components/ha_cellular_gateway/*.py
```

Do not disable dry-run until a supported USB3 NIC is attached and the
documented management, routing, IPv6 and firewall safety gates pass.
