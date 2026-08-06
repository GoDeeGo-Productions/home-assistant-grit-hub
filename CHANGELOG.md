# Changelog

All notable project changes are recorded here. This project uses semantic
versioning for public releases.

## Unreleased

### Fixed

- Replaced the GRITLock command-owned generation IDs and retained result map with
  one continuous immutable observed-state channel. Startup `/sts` or `/tel`
  `gls` and naturally quiet-settled live `/gl` bursts now publish through the
  same displayed-state authority; startup evidence remains ineligible for
  command confirmation.
- GRITLock Lock and Unlock now capture the MQTT connection generation and
  receive sequence before sending the explicit desired-state REST request, then
  wait for a matching newer `live_gl` observation on that same channel. A
  matching observation received while REST is still awaiting is eligible,
  while HTTP success, stale state, startup status, disconnect, disagreement,
  and timeout fail closed.
- Live `/gl` participant selection is based only on the current bounded burst:
  use the fresh `gte=1` subset when nonempty, otherwise use every fresh observed
  all-`gte=0` trigger. Sparse one-frame all-`gte=0` evidence is supported and
  REST participant metadata cannot redefine an active live burst. Incomplete
  evidence and command failure preserve the last valid state; complete
  disagreement and disconnect invalidate it.
- Corrected bounded current-connection GRITLock startup promotion when valid REST
  participant metadata names a trigger that does not report current `/sts` or
  `/tel` `gls`. A fully represented REST set remains exact; otherwise the latest
  strict `gls` from at most 64 observed reporters settles after 250 ms quiet and
  can publish before the five-second window expires. Messages without `gls` are
  ignored. Dion behavior, live `/gl` evaluation, commands, gates, and RFID are
  unchanged.

## 0.1.1 — 2026-08-05

### Fixed

- Made GRITLock compatible with trigger `/gl` messages that report `gte=0`:
  `gls` remains the authoritative live state and `gte` is advisory only. Valid
  REST participant metadata takes precedence; otherwise the exact bounded set
  observed in the fresh quiet-settled `/gl` generation defines participants.
  Empty, incomplete, contradictory, stale, overflowing, timed-out, or unsettled
  generations continue to fail closed.

Released as [GRIT Hub for Home Assistant v0.1.1](https://github.com/GoDeeGo-Productions/home-assistant-grit-hub/releases/tag/v0.1.1)
on 2026-08-05. The release passed the all-`gte=0` installation but exposed a
mixed-installation regression and is superseded by the corrective v0.1.2
process.

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
