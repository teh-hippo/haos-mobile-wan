# HAOS Mobile WAN

Use Home Assistant OS as a vendor-neutral mobile WAN gateway:

- `wlan0` connects to a phone hotspot, either from an existing HAOS profile or
  app-managed hotspot credentials;
- optional `iphone_usb` pairs with an iPhone and uses app-owned USB tethering
  over `ipheth`;
- a USB Ethernet adapter connects to a router WAN port;
- the app provides isolated DHCP, policy routing, firewalling and NAT.

The app starts with manual boot, disabled mode and dry-run enabled. Read the
[app documentation](DOCS.md) before changing those safeguards.
