# Changelog

All notable project changes are recorded here. This project uses semantic
versioning for public releases.

## Unreleased

No unreleased changes are recorded.

## 0.1.1 — Pending release

### Fixed

- Made GRITLock compatible with trigger `/gl` messages that report `gte=0`:
  `gls` remains the authoritative live state and `gte` is advisory only. Valid
  REST participant metadata takes precedence; otherwise the exact bounded set
  observed in the fresh quiet-settled `/gl` generation defines participants.
  Empty, incomplete, contradictory, stale, overflowing, timed-out, or unsettled
  generations continue to fail closed.

This release candidate has not yet been tagged or published.

## 0.1.0 — 2026-08-04

### Changed

- Recorded final transferred-repository live acceptance and verified repository
  security settings.
- Prepared publication documentation, security guidance, repository metadata,
  and offline documentation validation.
- Reduced benign unsupported MQTT-object logging from warning to debug while
  retaining warnings for malformed input.
- Made authenticated REST requests fail closed on HTTP redirects.

### Added

- HACS custom-integration packaging and config-flow localization.
- Authenticated current-hub discovery using `GET /api/hub`, with broker-only
  fallback when the API omits a usable LAN address.
- Direct subscribe-only MQTT v3.1.1 client with bounded lifecycle, input
  validation, exact successful SUBACK readiness, and no publish path.
- Gate covers with MQTT startup hydration, immediate external updates, and
  post-command MQTT confirmation.
- Per-reader RFID locks using authoritative individual REST detail and bounded
  MQTT-triggered invalidation refresh.
- System GRITLock using bounded MQTT trigger consensus with provisional strict
  REST startup state.
- Collector switches using individual REST detail and transition-aware command
  confirmation.
- Hub controls and diagnostics, including LED brightness, connectivity,
  software information, refresh, restart, and disabled-by-default reboot.
- Reconfiguration for API token rotation and MQTT settings while preserving
  config-entry, device, and entity identity.
- Deterministic network-free tests and HACS, Hassfest, and unit-test workflows.

### Security and privacy

- Opaque bounded bearer-token handling shared by production and diagnostic code.
- Sanitized REST and MQTT data retention, bounded generic logging, and no raw
  response/payload entity attributes.
- Redirect refusal for bearer-authenticated requests and diagnostics.
- No arbitrary HTTP endpoint service and no MQTT publishing.

Released as [GRIT Hub for Home Assistant v0.1.0](https://github.com/GoDeeGo-Productions/home-assistant-grit-hub/releases/tag/v0.1.0)
on 2026-08-04.
