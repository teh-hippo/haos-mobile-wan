# Changelog

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
