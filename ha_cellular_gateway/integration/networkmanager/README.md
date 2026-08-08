# NetworkManager integration lab

This rootful Docker lab runs production NetworkManager code against a real
daemon, D-Bus, DHCP peers, routes and app-owned profiles.

```sh
./ha_cellular_gateway/integration/networkmanager/run.sh
```

It covers inert profile creation, autoconnect prevention, profile ownership,
foreign-profile displacement, recovery markers, lease isolation, cleanup and
the negative control that proves an ordinary profile can leak a default route
into the main table.

The synthetic veth lacks Wi-Fi hardware identity, so the harness substitutes
only the unavailable radio and device identity reads. NetworkManager
mutations, D-Bus settings, routes and cleanup remain real. The synthetic Wi-Fi
secret is never printed.

The lab has no network, host mounts or ports. It requires rootful Docker,
Compose, `NET_ADMIN` and `NET_RAW`. Logs are written under `logs/`.
