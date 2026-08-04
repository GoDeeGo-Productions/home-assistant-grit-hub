# Changelog

All notable project changes are recorded here. This project uses semantic
versioning for public releases.

## Unreleased

- Recorded final transferred-repository live acceptance and verified repository
  security settings.
- Prepared publication documentation, security guidance, repository
  metadata, and offline documentation validation.
- Reduced benign unsupported MQTT-object logging from warning to debug while
  retaining warnings for malformed input.
- Made authenticated REST requests fail closed on HTTP redirects.

## 0.1.0 — Pending release

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

`0.1.0` has not yet been tagged or published. See the
[release checklist](docs/RELEASE_CHECKLIST.md).
