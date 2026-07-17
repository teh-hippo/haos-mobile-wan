# Changelog

## 0.8.1

- Keep USB device absence as healthy waiting when the runtime records more than
  one transient diagnostic. The aggregate diagnostic is no longer reclassified
  as a generic actionable error.

## 0.8.0

- Make Disabled genuinely dormant. The app no longer provisions or inspects
  mobile upstreams, starts iPhone helpers or probes the Internet while disabled.
  USB setup now begins only after a physical Apple device is detected.
- Add a configurable automatic shutdown. After an enabled gateway has no active
  path for 30 minutes by default, it persists Enabled off and tears down the
  gateway. Set the delay to 0 to disable automatic shutdown.
- Replace the gateway states with Disabled, Waiting, Connecting, Connected and
  Error. Waiting identifies the configured source, while Connected now means
  that the gateway path is applied independently of the Internet health probe.
- Replace Last error and Safety checks with a positive Health sensor reporting
  Healthy or Attention needed, with actionable issues in its attributes.
- Show Not connected instead of Offline for an unavailable public IP, and add
  the pending auto-disable deadline to Gateway state attributes.
- Remove the unused control POST endpoints. The MQTT and diagnostic HTTP
  surfaces are read-only; use the app Enabled option to activate the gateway.

## 0.7.1

- Keep idle text diagnostics as explicit Home Assistant states. "Last error"
  now reads "No error", and an absent downstream interface reads "Not present",
  instead of Home Assistant interpreting "None" as an unknown state.

## 0.7.0

- Expose the gateway over MQTT discovery as status-only monitoring entities,
  with no Home Assistant controls. Continue to control the gateway through the
  add-on options. This removes the earlier Enabled switch and Reapply gateway
  state button; the enabled state is now a read-only "Gateway enabled" binary
  sensor and the mobile connection is a read-only "Connection method" sensor.
- Show friendlier statuses and labels: enum sensors publish human-readable
  values such as "Waiting for device", "Connected" and "USB (iPhone)", the
  upstream health sensor is named "Internet available" and the active
  connection sensor is named "Connected via".
- Stop showing "unknown" for idle diagnostics: the public IP sensor reports
  "Offline" when there is no upstream, the downstream interface sensor reports
  "None" when no adapter is bound, and a missing active connection reads
  "Not connected".
- Stop reporting normal waiting as a fault. While the add-on is enabled and
  waiting, for example for a trusted iPhone or for the Wi-Fi hotspot to
  associate, the gateway state reads "Connecting" and the "Last error" sensor
  has no active fault. The "Last error" sensor reflects genuine non-transient
  faults only, while the safety checks sensor keeps the full raw diagnostics.

## 0.6.1

- Fix the MQTT broker credential lookup: the Supervisor request sent a
  malformed authorization header, so the add-on could not read the MQTT
  service and started without discovery.

## 0.6.0

- Publish the gateway device and entities to Home Assistant through built-in
  MQTT discovery, so the add-on no longer needs a custom integration and
  updates no longer require a Home Assistant reload. Requires the MQTT
  integration and a broker such as the Mosquitto add-on.
- Retire the bundled custom integration; the sensors, binary sensors, the
  enable switch and the reconcile button are now provided over MQTT with
  equivalent metadata. This is a breaking change: the old integration entities
  are replaced by MQTT-discovered entities with new entity ids, so remove the
  custom integration after updating.
- Keep the `/health` and `/v2/status` endpoints for manual diagnostics.

## 0.5.0

- Recover the management baseline at runtime, so a transient host networking
  problem during startup no longer leaves the gateway disabled until a restart.
- Add a gateway state sensor that reports disabled, offline, connecting or
  connected at a glance, alongside the configured and active connection.
- Distinguish a disabled Wi-Fi adapter and an enabled but unassociated hotspot
  from a generic inactive upstream, and note that 802.11 status codes stay in
  the host supplicant logs.
- Prune obsolete add-on options left behind by earlier versions after an
  upgrade, so an upgraded install matches a fresh one.
- Route logging through the standard framework: per-request API logging moves
  to debug, and iPhone USB and Wi-Fi connect and disconnect events log at info.
- Start the app under its AppArmor profile in CI so a broken runtime is caught
  before release.

## 0.4.9

- Run dnsmasq with its supervised `--no-daemon` mode so it does not attempt a
  user or group transition unavailable inside the confined app container.

## 0.4.8

- Keep dnsmasq as root inside the AppArmor-confined container because the app
  intentionally does not grant host `SETGID`.

## 0.4.7

- Surface an immediate router DHCP process exit instead of repeatedly
  reapplying gateway state without an error.
- Send dnsmasq diagnostics to the managed app log.

## 0.4.6

- Read the iPhone gateway from NetworkManager's table 202 default route because
  `IP4.GATEWAY` is empty when DHCP routes use a non-main table.

## 0.4.5

- Use NetworkManager's documented single-connection default instead of
  repeatedly setting a value that HAOS serialises as default.

## 0.4.4

- Reconcile the persistent NetworkManager profile once per app process instead
  of rewriting it on every five-second status cycle.
- Log only the names of drifted profile fields when a startup repair is needed.

## 0.4.3

- Hand iPhone USB discovery, DHCP, address, renewals and DHCP-derived routes to
  host NetworkManager through a persistent `haos-mobile-wan-iphone` profile that
  matches the `ipheth` driver.
- Keep the NetworkManager DHCP routes in dedicated table 202 and keep the
  app-owned policy table 201 unchanged.
- Fail closed when a foreign profile owns the interface, a phone default reaches
  the main table, a rule selects table 202, the lease is invalid or a second
  device appears.
- Add the `host_dbus` permission, the Alpine `networkmanager-cli` package and a
  scoped NetworkManager D-Bus AppArmor rule, and remove the app-owned BusyBox
  DHCP client.
- This is a breaking permission and architecture update. The app leaves other
  NetworkManager profiles untouched and fails closed if one remains active.

## 0.4.2

- Serialise iPhone DHCP address changes with lease ownership checks so the app
  cannot mistake its own lease for host-managed state.
- Remove only the exact app-owned USB address during DHCP renewal and cleanup.
- Treat an `ipheth` interface disappearing during inspection as a normal
  hot-plug transition.

## 0.4.1

- Keep a failed iPhone pairing request open long enough to accept the Trust
  prompt instead of reopening it every reconciliation cycle.
- Allow the BusyBox DHCP client and its lease helper to run under AppArmor.

## 0.4.0

- Replace gateway mode and dry-run with a single Enabled control.
- Add USB-preferred Wi-Fi fallback with automatic return to iPhone USB.
- Block fallback when USB ownership is uncertain and remove only the exact
  app-owned USB address during cleanup.
- Show configured and active mobile connections in the optional integration.
- Simplify app settings and move the router WAN address to optional advanced
  configuration.
- Move the breaking app and integration contract to API v2.
- Rewrite the user documentation around providing fallback WAN service.

## 0.3.19

- Allow the iPhone USB preflight to enumerate the exact USB sysfs directory
  under AppArmor.

## 0.3.18

- Add optional masked hotspot credentials and apply the Wi-Fi profile through
  Supervisor at app startup.
- Limit app modes to direct disabled and active control.
- Split the app bootstrap, discovery, interface, firewall, policy and upstream
  helpers into smaller modules.

## 0.3.17

- Install the iPhone command-line tools required for USB pairing and fail the
  image build if either pairing executable is missing.

## 0.3.16

- Mark the live-commissioned 0.3 baseline as the current release for continued
  pre-1.0 testing.

## 0.3.15

- Keep the dnsmasq pidfile under the app-owned runtime directory.
- Allow dnsmasq to read the standard group database.

## 0.3.14

- Allow dnsmasq to bind its DHCP service port under AppArmor.

## 0.3.13

- Allow creation of the gateway runtime directory under AppArmor.

## 0.3.12

- Allow unavoidable IPv6 link-local addresses while rejecting routed IPv6.

## 0.3.11

- Treat an unused Linux policy table as empty during preflight inspection.

## 0.3.10

- Allow the final resolver configuration file reported by AppArmor.

## 0.3.9

- Allow the runtime name-resolution and CA files reported by AppArmor.

## 0.3.8

- Allow the network inspection paths reported by the live AppArmor audit.

## 0.3.7

- Allow the two package and SSL paths reported by the runtime AppArmor audit.

## 0.3.6

- Execute the gateway script directly without package discovery at startup.

## 0.3.5

- Allow AppArmor to traverse the gateway package directory.

## 0.3.4

- Set the Python package search path explicitly for the gateway runtime.

## 0.3.3

- Start from the image root so Python can import the gateway package.

## 0.3.2

- Override the base image entrypoint so the gateway starts without `/init`.

## 0.3.1

- Start the gateway process directly instead of invoking the unused inherited
  s6 entrypoint under the enforced AppArmor profile.

## 0.3.0

- Reduce the normal app form to mode, dry-run, upstream mode and downstream
  network choices, with optional hotspot and adapter overrides.
- Detect the sole management default route and a single USB Ethernet adapter
  instead of asking users to copy host identity into app options.
- Own one exact transient downstream address and remove it with DHCP, policy
  and forwarding state on rollback, failure or shutdown.
- Keep the downstream host-ingress guard while the app runs, then remove it on
  graceful shutdown.
- Limit the downstream router to one five-minute DHCP lease.
- Arm the rollback deadline when trial mode is first loaded from app options.
- Allow 30 seconds for graceful Supervisor shutdown cleanup.

## 0.2.0

- Protect HAOS host-local services from the downstream WAN interface.
- Make policy routing and cleanup non-destructive to unrelated host rules.
- Fail closed when host safety inspection fails.
- Persist trial deadlines across app restarts.
- Cache health and safety status outside API requests.
- Prevent duplicate optional integration entries when Supervisor discovery
  updates a manually added connection.
- Redact the optional integration URL from diagnostics output.
- Keep the optional integration's mode entity readable in steady-state active
  mode without allowing it to bypass the documented trial workflow.
- Remove the non-functional hotspot scan and unused host D-Bus access.
- Add translated options and a complete HAOS commissioning guide.
- Split the gateway engine into focused configuration, safety, policy,
  firewall, DHCP and persistent-state modules.
- Keep Wi-Fi hotspot mode as the default while adding an experimental
  `iphone_usb` upstream mode.
- Add guided iPhone USB trust, `ipheth` discovery and DHCP preflight with
  persistent pairing records under `/data/lockdown`.
- Add the enforced AppArmor profile and keep the app to the audited
  `host_network`, `hassio_api`, `NET_ADMIN`, `NET_RAW` and `usb` permission
  set, without `full_access`, host D-Bus or `udev`.

## 0.1.1

- Recover automatically after transient interface loss.
- Clean partial activation state before retrying.
- Preserve the trial deadline while runtime safety recovers.

## 0.1.0

- Initial public prototype.
