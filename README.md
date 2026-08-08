# HAOS Mobile WAN

HAOS Mobile WAN gives a router a fallback Internet connection through Home
Assistant OS.

It supports:

- a phone Wi-Fi hotspot;
- iPhone USB tethering;
- Android RNDIS, CDC Ethernet, CDC NCM and similar USB tethering;
- automatic USB-preferred Wi-Fi fallback;
- an isolated USB Ethernet connection from HAOS to the router WAN.

```text
Phone -> Home Assistant OS -> USB Ethernet -> Router WAN -> Home network
```

Home Assistant keeps its normal management connection. Mobile traffic uses
separate routing tables and cannot fall back through the management network.
The app fails closed and removes only network state that it owns.

## Install

1. Open **Settings > Apps > App store**.
2. Open **Repositories** and add
   `https://github.com/teh-hippo/haos-mobile-wan`.
3. Install **Mobile WAN**.
4. Leave the app on manual boot and complete the
   [commissioning guide](ha_cellular_gateway/DOCS.md) before connecting the
   router WAN cable.

Released versions use signed aarch64 images from GHCR. The HAOS host does not
build the app locally.

## Requirements

- Home Assistant OS on `aarch64`;
- one dedicated USB Ethernet adapter for the router WAN;
- a dedicated Wi-Fi adapter when a hotspot mode is selected;
- the Home Assistant MQTT integration and an MQTT broker for entities;
- an Ethernet-style DHCP interface for generic USB tethering.

QMI and MBIM modems that require modem setup are not supported. Only IPv4
gateway service is provided.

## Home Assistant

The app publishes a **HAOS Mobile WAN** MQTT device with gateway, health,
connection, USB, interface and Internet-status entities. The MQTT entities are
monitoring-only.

Start and stop the app through **Settings > Apps** or Home Assistant's
`hassio.addon_start` and `hassio.addon_stop` actions. The
[dashboard example](ha_cellular_gateway/DOCS.md#dashboard-example) shows
conditional Start and Stop controls alongside the status entities.

## Safety

The app uses host networking, NetworkManager D-Bus, `NET_ADMIN`, `NET_RAW`,
Supervisor manager access and USB access because it manages real HAOS
interfaces, routing, firewall rules, DHCP and optional iPhone pairing. An
enforced AppArmor profile limits that access to the required services, tools
and paths.

Read the [operational documentation](ha_cellular_gateway/DOCS.md) before
starting the gateway. Report security issues through
[SECURITY.md](SECURITY.md).

## Development

The authoritative checks are in
[`.github/workflows/validate.yml`](.github/workflows/validate.yml). The primary
local commands are:

```sh
uv sync --frozen

PYTHONPATH=ha_cellular_gateway \
  uv run coverage run -m unittest discover -s ha_cellular_gateway/tests -v
uv run coverage report
uv run ruff check .
uv run ruff format --check .
uv run ruff check --select C901 --config 'lint.mccabe.max-complexity=15' \
  ha_cellular_gateway/rootfs/app
uv run mypy ha_cellular_gateway/rootfs/app tools
uv run python -m tools.distribution_contract
```

The NetworkManager and QEMU integration labs remain required release gates.
Their local commands and host requirements are documented in
[`integration/networkmanager`](ha_cellular_gateway/integration/networkmanager/README.md)
and
[`integration/networkmanager_wifi`](ha_cellular_gateway/integration/networkmanager_wifi/README.md).

## Releases

[`.github/workflows/release.yml`](.github/workflows/release.yml) verifies the
exact tested commit, signed image, SBOM and integration gates before creating a
release. Changes to the shipped app payload must increase
`ha_cellular_gateway/config.yaml` and add the matching section to
`ha_cellular_gateway/CHANGELOG.md`.
