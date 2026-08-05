# Entity reference

This document inventories the entity platforms implemented by the `grit_hub`
custom integration. Entity creation depends on the devices and fields returned
by the configured GRIT system.

Forwarded platforms are `sensor`, `binary_sensor`, `switch`, `cover`, `button`,
`lock`, and `number`.

## State-authority summary

| Device or control | Home Assistant platform | Displayed-state authority | Command confirmation |
| --- | --- | --- | --- |
| Gate | `cover` | MQTT live state | Newer matching MQTT observation after the pre-command boundary |
| RFID reader | `lock` | Individual `GET /api/rfid/{id}` strict `state` | Newer matching individual REST generation |
| GRITLock | `lock` | Settled trigger `/gl` MQTT consensus; strict REST trigger fields provisionally at startup | Fresh settled MQTT generation |
| Collector | `switch` | Individual collector detail, with proven MQTT supplementation | Newer online, settled matching individual REST detail |
| Solenoid, latch, powerbank | `switch` | Existing collection/reconciliation implementation | Bounded full coordinator refresh; no collector contract is claimed |
| System LED brightness | `number` | Sanitized hub REST field | Newer full hub refresh with matching value |

Unknown or incomplete authoritative evidence remains Unknown. HTTP success alone
does not confirm a state-changing command, and no entity publishes optimistic
state.

## Covers

### Gate

One `CoverEntity` with device class `gate` is created per discovered gate.
Retained MQTT can hydrate startup position/open state, and GRIT-application or
physical changes update it immediately. Open and close use the bounded REST
state route, capture the MQTT sequence before the command, and require a newer
matching MQTT observation. There is no unproven REST gate-state fallback.
Availability requires a successful REST update, an active MQTT subscription,
and no explicit offline report. Attributes are restricted to bounded
allowlisted diagnostics.

## Locks

### GRITLock

One system-wide `LockEntity` is created. `PUT /api/hub/lockout` receives
`{"state": true}` for Lock and `{"state": false}` for Unlock. Before MQTT
authority settles, strict `gritLockEnabled` and `gritLockState` values from
trigger inventory may provide provisional startup state.

Exact `trigger/<id>/gl` messages provide live authority, and `gls` is the live
lock state. A nonempty, complete, valid REST `gritLockEnabled` set defines the
required participants when available; an empty set does not identify
participants and uses MQTT fallback. Otherwise each fresh quiet-settled
generation uses exactly its `gte=1` trigger subset when at least one exists; an
all-`gte=0` generation uses all of its fresh observed triggers. MQTT-derived
participants are not carried into another generation. Every selected
observation must agree on `gls`; zero observations, participant-limit overflow,
missing REST participants, disagreement, stale evidence, timeout, generation
replacement, or an unsettled generation produces Unknown or fails
confirmation.

A command opens a clean generation at the pre-command MQTT boundary and is
confirmed only by its newer naturally settled generation. HTTP success and the
currently displayed state are never enough, including for a no-op command. A
valid settled result immediately notifies the entity, so Locked exposes Unlock
and Unlocked exposes Lock without waiting for REST polling. MQTT disconnect
discards incomplete generations and may return to valid provisional REST state.

### RFID reader

One `LockEntity` is created per uniquely identified RFID reader. The strict
boolean `state` from `GET /api/rfid/{id}` is authoritative:

- `true` means enabled/unlocked;
- `false` means disabled/locked.

Lock sends REST state `false`; Unlock sends REST state `true`. Confirmation
requires a newer matching individual detail read. Collection `state` and
`lockout` are not used as lock state. RFID MQTT `sts` is diagnostic-only, while
exact `s` and `st` types invalidate the cached state and schedule a bounded,
debounced individual REST refresh; their payload values do not determine the
lock state.

An explicitly offline reader is unavailable. A temporary failed read preserves
the last valid state internally without inventing a new one. No signed-in user,
cardholder, card number, or other personal data is ingested into entity state or
attributes.

## Switches

One `SwitchEntity` may be created for each discovered collector, solenoid,
latch, and powerbank.

### Collector

Collector state comes from strict individual `GET /api/collector/{id}` fields,
including `state`, transition fields, and online status. A command captures the
individual-detail generation before sending REST state `true` or `false`, then
performs bounded detail reads. It waits through a legitimate transition and
succeeds only for a newer, online, settled matching state. This accommodates the
proven delayed collector shutdown without claiming success too early.

### Other switch types

Solenoid, latch, and powerbank retain the existing generic REST collection
refresh confirmation. The integration does not claim collector transition
semantics for them. Their availability also depends on successful REST and MQTT
connectivity and no explicit offline observation.

## Numbers

### System LED Brightness

A configuration-category `NumberEntity` provides a 0–100 percent slider in
whole-number steps. It writes only the documented hub setting and confirms it
with a newer full hub refresh. No matching refreshed value means failure rather
than an assumed state.

## Buttons

| Entity | Category | Behavior and limitations |
| --- | --- | --- |
| Refresh All | Configuration | Requests an immediate coordinator refresh; no device command |
| Restart GRIT Service | Configuration | Calls the bounded GRIT service restart route |
| Reboot Hub | Configuration; disabled by default | Reboots the physical hub; enable and use only with explicit site authorization |
| Device Refresh | Configuration, per device | Calls the bounded device refresh route, then refreshes coordinator state |
| Device Locate | Configuration, per device | Calls the bounded locate route and may cause physical device activity |

## Binary sensors

All are diagnostic entities:

- **Online** — Home Assistant coordinator REST update success.
- **Internet Connectivity** — strict sanitized hub
  `connectedToInternet` value.
- **Physical Hub Buttons Disabled** — strict sanitized hub
  `disableHubButtons` value.
- **MQTT Connection** — dedicated client connection/subscription state; always
  available so broker loss remains visible.
- **MQTT Online** — per-device bounded MQTT online observation, available only
  after a supported value has been observed.

## Sensors

Hub diagnostic sensors are **Status**, **Device Count**, **Hub IP Address**,
**Hub Software Version**, and **Software Branch**. Generic status sensors may be
created for air-quality, presence, pressure, dustbin, magswipe, scanner,
trigger, and extender devices.

Every uniquely discovered device may also receive these diagnostics when a
supported value exists:

- **MQTT RSSI** — signal strength in dBm;
- **MQTT Firmware** — bounded firmware text;
- **MQTT Last Received** — timestamp of the last accepted sanitized message.

Entity attributes are limited to the integration's small scalar allowlist; raw
REST objects, raw MQTT payloads, complete topics, and error responses are not
exposed.

## Services

`grit_hub.device_command`, `grit_hub.refresh_device`, and
`grit_hub.locate_device` are registered. They accept bounded path components,
not arbitrary HTTP methods or arbitrary endpoint paths. They can still cause
physical activity and should be called only with a verified target and an
explicitly authorized site procedure.

No MQTT publishing service or general arbitrary-endpoint service exists.

See [Architecture](ARCHITECTURE.md), [Troubleshooting](TROUBLESHOOTING.md), or
return to the [README](../README.md).
