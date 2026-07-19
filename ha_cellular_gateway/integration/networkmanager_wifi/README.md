# NetworkManager Wi-Fi integration lab

This on-demand lab boots a disposable Debian guest with QEMU/KVM, creates two
`mac80211_hwsim` radios, runs a WPA2 access point in a network namespace, and
exercises the production Wi-Fi code against real NetworkManager and kernel
state.

It requires x86_64, `/dev/kvm`, QEMU, `genisoimage`, SSH and rsync. It does not
create a Proxmox VM, bridge, tap or LAN client. QEMU user networking exposes
only a loopback SSH forward.

`mac80211_hwsim` does not provide NetworkManager's stable hardware
`GENERAL.PATH`. The guest test synthesises only that identity; scans, WPA,
profiles, D-Bus metadata, routes, displacement and cleanup remain real.

The guest also exposes QEMU's `usb-net` device through the real Linux
`cdc_ether` driver. The suite creates the app profile before binding the
driver, then validates generic USB-only, USB-preferred Wi-Fi fallback, device
removal, device return and table-202 cleanup.

Run the fixed-code suite:

```sh
./ha_cellular_gateway/integration/networkmanager_wifi/run.sh
```

Run the v0.10.0 negative control from an exported source tree:

```sh
LAB_EXPECT=legacy ./ha_cellular_gateway/integration/networkmanager_wifi/run.sh
```

On hippoxmox, reuse the verified local cloud image:

```sh
QEMU_BASE_IMAGE=/var/lib/vz/template/iso/debian-13-generic-amd64.qcow2 \
QEMU_BASE_IMAGE_SHA512=aca6eefc7b87faddad617b197fb621c44cc2c440f7097d78ac06e113f78177f6b7a1a39a581fbb24c2513354ab6938e63e78730259ce204b53452e8186f53a37 \
./ha_cellular_gateway/integration/networkmanager_wifi/run.sh
```

Logs are retained under `logs/`. The synthetic PSK is redacted from retained
configuration and process logs.
