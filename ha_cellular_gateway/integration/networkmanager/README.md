# NetworkManager integration lab

Run the lab with rootful Docker and the Compose plugin:

```sh
./ha_cellular_gateway/integration/networkmanager/run.sh
```

It builds from the add-on's Home Assistant Alpine base, copies the production
app code, and installs the same `networkmanager-cli` package family with the
NetworkManager daemon. The one isolated service has no network, host mounts or
ports, and adds `NET_ADMIN` and `NET_RAW` to Docker's default capability set
(no minimal `cap_drop` has been verified for this daemon stack). It creates an
in-container veth pair and DHCP peer, then exercises real `nmcli`, D-Bus,
inventory, profiles and custodianship through production code. Logs are written
to `logs/compose.log`.

The veth-only test variants cover DHCP and routing control-plane behaviour.
They do not cover Wi-Fi association, SSIDs, WPA, ipheth, iPhone trust or mobile
carrier behaviour. Those remain HAOS hardware acceptance gates. Rootless
Docker and Podman are not equivalent to this rootful runtime test.
