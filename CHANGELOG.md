# Changelog

## 0.1.2 — 2026-11-18

- Refresh the switch every second after `/launch` or `/cancel` until the host
  reports the expected state, instead of waiting for the next scheduled poll.

## 0.1.1 — 2026-11-18

- Fix the switch staying at its setup value until the integration is reloaded:
  the entity now extends `CoordinatorEntity` and subscribes to coordinator updates.
- Build the mutual-TLS context in a worker thread, removing Home Assistant's
  blocking-call warnings for `load_cert_chain` and the temporary PEM directory.
- Add brand icons and point `manifest.json` metadata at this repository.

## 0.1.0

- Initial MoonScreen integration.
- Moonlight PIN pairing (four phases, AES-128-ECB without padding, RSA PKCS#1 v1.5).
- Pinned server certificate and mutual TLS for `/serverinfo`, `/applist`, `/launch`, `/cancel`.
- `switch.电脑屏幕`: OFF starts Desktop with `useVdd=1` and the configured `mode`; ON calls `/cancel`.
- State polling via `/serverinfo`, optional Web UI session list and active-stream guard.
- Options for resolution/FPS, Desktop app name, poll interval, Web UI credentials.
- Diagnostics redaction, fake Sunshine test double, protocol documentation and live check tool.
