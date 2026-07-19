# NetworkManager integration lab

Run the lab with rootful Docker and the Compose plugin:

```sh
./ha_cellular_gateway/integration/networkmanager/run.sh
```

It builds from the add-on's Home Assistant Alpine base, copies the production
app code, and installs the same `networkmanager-cli` package family with the
NetworkManager daemon. The one isolated service has no network, host mounts or
ports, and adds `NET_ADMIN` and `NET_RAW` to Docker's default capability set
(no minimal `cap_drop` has been verified for this daemon stack). The daemon
starts before any test device exists; each test then realises its own in-veth
pair and DHCP peer so it controls NetworkManager's one-time
`have_connection_for_device` gate, and exercises real `nmcli`, D-Bus, inventory,
profiles and custodianship through production code. Logs are written to
`logs/compose.log`.

The lab does not set `no-auto-default`; HAOS does not either. NetworkManager's
real auto-default behaviour is therefore in play, which is exactly why each test
installs its intended profile before the carrier-up veth is realised.

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

Paired inert-creation controls run through the real realisation gate. A
mandatory negative control installs an autoconnectable profile with no route
isolation before the device is realised and proves NetworkManager auto-activates
it and leaks a default into the main table, so the positive control cannot pass
vacuously. The positive control installs the profile through production
`NmProfile.create()` before realisation, confirms it stays inactive with no
address, lease or default, then activates it explicitly and confirms the default
lands only in table 202. It also deletes and recreates the profile over the
still-realised device and confirms no default is wired in the gap.

Honest safety cases cover scenarios the production inert-create fix does not
address: a device realised with no matching profile, and a link re-realised
during a profile gap. If NetworkManager generates a default wired connection and
wires a default into the main table, the lab asserts the app's kernel-truth
main-table safety detects it fail-closed. It makes no claim that the production
fix prevents those separate scenarios. Every fixed profile, generated
connection, route, rule and the veth are removed on exit.

The veth-only test variants do not cover Wi-Fi association, SSIDs, WPA, ipheth,
iPhone trust or mobile carrier behaviour. Those remain HAOS hardware acceptance
gates. Rootless Docker and Podman are not equivalent to this rootful runtime
test.
