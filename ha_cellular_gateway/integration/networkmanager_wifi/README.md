# NetworkManager Wi-Fi integration lab

This on-demand QEMU/KVM lab boots a disposable Debian guest with simulated
Wi-Fi radios, a WPA2 access point and a CDC Ethernet USB device. It exercises
production Wi-Fi, generic USB, fallback and cleanup code against real
NetworkManager and kernel state.

Requirements are x86_64, `/dev/kvm`, QEMU, `genisoimage`, SSH and rsync.
The default Debian `trixie/latest` image is verified against the SHA-512
checksum published beside the image. Set `QEMU_IMAGE_SHA512` to require a
specific image digest or `QEMU_IMAGE_SHA512_URL` when using an image mirror
with a separate checksum manifest.

```sh
./ha_cellular_gateway/integration/networkmanager_wifi/run.sh
```

Run the historical negative control from an exported v0.10.0 tree with:

```sh
LAB_EXPECT=legacy ./ha_cellular_gateway/integration/networkmanager_wifi/run.sh
```

The guest synthesises only the stable hardware identity that
`mac80211_hwsim` does not provide. Scanning, WPA, profiles, D-Bus metadata,
routes, source switching and cleanup remain real. The lab does not create host
bridges, taps or LAN clients. Logs are retained under `logs/` with the
synthetic PSK redacted.
