# HAOS Mobile WAN

Use Home Assistant OS to provide a fallback WAN connection to your router.

- Connect through a phone Wi-Fi hotspot.
- Use iPhone USB tethering.
- Use generic Android RNDIS, CDC or Ethernet-style USB tethering.
- Prefer USB and fall back automatically to Wi-Fi.
- Hand the connection to the router through an isolated USB Ethernet adapter.

The app activates the gateway as soon as it starts and fails closed if its
network safety checks do not pass. Read the [app documentation](DOCS.md) before
you start the gateway.
