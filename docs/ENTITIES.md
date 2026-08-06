# Entity reference

This document inventories the entity platforms implemented by the `grit_hub`
custom integration. Entity creation depends on the devices and fields returned
by the configured GRIT system.

Forwarded platforms are `sensor`, `binary_sensor`, `switch`, `cover`, `button`,
`lock`, and `number`.

## State-authority summary

| Device or control | Home Assistant platform | Displayed-state authority | Command confirmation |
| --- | --- | --- | --- |
| Gate | `cover` | MQTT live state, including fresh requested `/sts` or `/tel` startup telemetry | Newer matching MQTT observation after the pre-command boundary |
| RFID reader | `lock` | Individual `GET /api/rfid/{id}` strict `state` | Newer matching individual REST generation |
| GRITLock | `lock` | Latest immutable current-connection observation from startup status, settled live `/gl`, or disagreement | Matching fresh settled `live_gl` observation newer than the pre-command connection/sequence boundary |
| Collector | `switch` | Individual collector detail, with proven MQTT supplementation | Newer online, settled matching individual REST detail |
| Solenoid, latch, powerbank | `switch` | Existing collection/reconciliation implementation | Bounded full coordinator refresh; no collector contract is claimed |
| System LED brightness | `number` | Sanitized hub REST field | Newer full hub refresh with matching value |

Unknown or incomplete authoritative evidence remains Unknown. HTTP success alone
does not confirm a state-changing command, and no entity publishes optimistic
state.

## Covers

### Gate

One `CoverEntity` with device class `gate` is created per discovered gate.
After exact MQTT readiness, a bounded authenticated per-gate telemetry request
waits for a fresh `/sts` or `/tel` response. Its compact `p` field may be a
bounded number or numeric text and hydrates position/open state. `/req-tel` is a
request marker, not gate state. Later `/mv`, `/mv-d`, `/p`, `/s`, and `/st`
observations continue to update immediately. Open and close use the bounded REST
state route, capture the MQTT sequence before the command, and require a newer
matching MQTT observation. There is no unproven REST gate-state fallback and no
assumption that a retained MQTT status exists. A missing response leaves that
gate Unknown without erasing valid state accepted for another gate.
Availability requires a successful REST update, an active MQTT subscription,
and no explicit offline report. Attributes are restricted to bounded
allowlisted diagnostics.

## Locks

### GRITLock

One system-wide `LockEntity` is created. `PUT /api/hub/lockout` receives
`{"state": true}` for Lock and `{"state": false}` for Unlock. The entity is
never toggle-driven or optimistic. REST `gritLockState` is not displayed because
inventory freshness is unproven.

Displayed state derives from one latest immutable coordinator observation.
Strict current-connection trigger `/sts` or `/tel` `gls` may hydrate that field
at startup; `/tel` without `gls` does not count. Nonempty complete REST
`gritLockEnabled` metadata can select startup participants only. Otherwise the
bounded known triggers that actually report strict `gls` form the quiet-settled
startup fallback. Unanimous one is Locked, unanimous zero is Unlocked, and
complete disagreement is Unknown. Startup status is displayed-state authority
only and cannot confirm Lock or Unlock.

Exact `trigger/<id>/gl` messages provide continuous live authority. Each bounded
quiet-settled burst keeps only the latest valid observation per trigger. If any
fresh observation has `gte=1`, exactly the fresh `gte=1` subset participates. If
all fresh observations have `gte=0`, every fresh observed trigger participates,
including a sparse one-frame burst. Every selected observation must agree:
`gls=1` is locked (`True`), `gls=0` is unlocked (`False`), and exact `False` is
authority, not missing state. Complete disagreement publishes Unknown.
Malformed, incomplete, overflowing, or unsettled evidence preserves the last
valid state. REST participant metadata cannot redefine an active live burst.

A command captures MQTT connection generation and receive sequence before the
explicit REST desired-state request. It then waits against the same latest
observation channel for a naturally settled `live_gl` observation supported
entirely by sequences newer than the boundary. This accepts a matching frame
that arrives while REST is still awaiting and avoids lost wakeups by checking
before and after waiter registration. HTTP success, current displayed state,
startup status, stale evidence, an opposite state, disagreement, timeout,
disconnect, or reconnect cannot confirm. There are no command generation IDs or
retained command-result map.

No-op requests still send REST and require fresh matching live evidence.
Confirmation failure preserves the last valid displayed state unless explicit
disagreement or disconnect invalidates authority. A valid live observation
notifies the entity once, so Locked exposes Unlock and Unlocked exposes Lock
without waiting for REST polling. Unknown is unavailable. Gate and RFID entity
semantics are unchanged by this GRITLock refactor.

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
