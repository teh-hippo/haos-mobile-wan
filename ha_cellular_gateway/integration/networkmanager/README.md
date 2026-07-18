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

The veth has neither a Wi-Fi radio nor stable hardware `GENERAL.PATH` identity.
The harness therefore synthesises only an enabled radio read and a deterministic
veth identity when that path is absent. All ownership mutations and every other
read still execute through the real NetworkManager daemon: autoconnect gating,
foreign-profile displacement, the `user.data` recovery marker, D-Bus
`GetSettings`, DHCP, table routing, release, recovery and cleanup remain real.
Alpine's nmcli does not expose the `user` setting, so the marker is written,
read and cleared through the production `Settings.Connection` D-Bus helper.

A synthetic WPA-PSK Wi-Fi profile proves the marker is metadata-only: the lab
compares `GetSecrets` and `GetSettings` before and after writing and clearing
the marker to confirm the PSK and every other setting are preserved. The secret
is never printed.

The veth-only test variants do not cover Wi-Fi association, SSIDs, WPA, ipheth,
iPhone trust or mobile carrier behaviour. Those remain HAOS hardware acceptance
gates. Rootless Docker and Podman are not equivalent to this rootful runtime
test.
