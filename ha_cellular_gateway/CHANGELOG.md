# Changelog

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
