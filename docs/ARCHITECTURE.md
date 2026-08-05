# Architecture

GRIT Hub is a Home Assistant config-entry integration with authenticated REST
and a dedicated subscribe-only MQTT client. The coordinator combines bounded,
sanitized observations without assigning one protocol universal authority.

## Module map

| Module | Responsibility |
| --- | --- |
| `__init__.py` | Config-entry setup, readiness, services, platform forwarding, reload, and unload cleanup |
| `config_flow.py` | Initial authentication, discovery, MQTT validation, Advanced fallback, options, and reconfigure |
| `api.py` | Bounded REST methods, bearer authentication, redirect refusal, endpoint-safe errors, and response sanitization |
| `auth.py` | Shared opaque bearer-token validation and exact header construction |
| `discovery.py` | Bounded passive MQTT discovery/readiness validation |
| `mqtt_live.py` | Dynamic Paho import, lifecycle state, exact subscription, sanitization, and parsed-message callbacks |
| `coordinator.py` | Polling, ordering, source authority, confirmation generations, bounded refresh work, and cancellation |
| `hub.py` | Strict hub identifier, broker-address, and hub-field sanitization |
| `entity.py` | Shared device identity and bounded diagnostic attributes |
| Platform modules | Entity creation and explicit command/confirmation behavior |
| `const.py` | Configuration constants, platform/device lists, and retained imported/generated endpoint catalogue |

## Configuration and discovery

The normal config flow accepts an API base URL, raw opaque bearer token, and API
certificate-verification choice. The token is validated without trimming or
format assumptions and is sent only in the `Authorization` header. A bounded
authenticated `GET /api/hub` both proves integration access and returns the hub
identity.

A valid documented hub `id` becomes the MQTT topic hub ID. A valid returned
Ethernet address becomes the broker. If the address is missing, only that field
is requested; the hub ID and internal defaults are retained. Advanced settings
can override broker, port, topic hub ID, credentials, TLS, certificate
verification, keepalive, and REST interval.

Discovery performs no scan and no background retry. It connects to only the
configured candidate, never publishes, and fails closed if any bounded
validation step is incomplete.

## REST client

Every production request has an explicit total timeout. The client refuses HTTP
redirects so a bearer header is never forwarded to a redirect target. Error
responses are not read; exceptions contain only method, a bounded endpoint
identifier, and status where appropriate. Query values, object IDs, response
bodies, bearer tokens, headers, request bodies, and cookies are not logged.

REST response sanitizers retain only fields needed by current entities and
confirmation. Raw hub, health, collection, individual-detail, and error objects
are not retained. Health data is reduced to reachability. No Home Assistant
diagnostics-download platform is implemented.

## MQTT lifecycle and readiness

Paho is imported dynamically only when a client starts. Construction and module
import do not connect. Both paths use MQTT v3.1.1, QoS 0, and callback API
compatibility for Paho 2.1.0.

Config-flow discovery uses `connect_async()`, accepts its normal `None` result,
starts a temporary network loop, and subscribes exactly to:

`grit/<configured-hub-id>/+/+/#`

The established runtime `GritLiveMqtt` client uses bounded `connect()` and
network-loop lifecycle handling, and subscribes to `grit/+/+/+/#`. It delivers
only parsed bounded components; the coordinator requires an exact configured
hub-ID match before retaining any state. Neither path logs or retains the
complete topic.

Readiness in each path requires all of these:

1. successful connection reason code;
2. successful `subscribe()` return;
3. exact message-ID match between that call and a successful SUBACK;
4. no stop, disconnect, replacement, timeout, malformed acknowledgement, or
   stale callback before readiness is latched.

The early-SUBACK latch handles a synchronous `on_subscribe` callback that can
arrive before `subscribe()` returns its message ID. Obsolete callbacks must
belong to the active client or they are ignored generically. Stop is idempotent,
cancels partially started clients, leaves connection state false, and prevents
late callbacks from reviving it. Production code contains no MQTT publish path.

Inbound complete topics, topic components, and payload bytes have conservative
bounds. JSON must be an object and only supported bounded scalar fields survive
sanitization. Complete topics, broker addresses, hub/device IDs, credentials,
and payload bodies are not logged or retained.

## Coordinator and reconciliation

A normal poll defaults to 30 seconds. REST inventory remains bounded and the
last valid sanitized data is preserved when a particular refresh fails. MQTT
updates carry receive-sequence ordering so an older REST observation cannot
silently replace authoritative newer live state. Background telemetry and
individual-detail work is bounded by target count, concurrency, timeout, and
coalescing rules. Disconnect and unload cancel outstanding work and waiters.

The coordinator forwards only the fixed platform list: `sensor`,
`binary_sensor`, `switch`, `cover`, `button`, `lock`, and `number`. Failed setup
stops the MQTT client and cancels coordinator work before retry. Unload tears
down platforms, listeners, services when appropriate, MQTT loops, waiters, and
refresh tasks. Reconfigure validates first, updates the existing entry through
supported Home Assistant APIs, and reloads once.

## State authority

| State | Authoritative evidence |
| --- | --- |
| Gate | MQTT live state; REST issues commands but does not hydrate or confirm gate state |
| RFID | Strict individual `GET /api/rfid/{id}` boolean `state`; exact MQTT `s`/`st` only invalidates and requests refresh |
| GRITLock | Settled unanimous MQTT `/gl` generation; strict REST trigger consensus is provisional at startup or after disconnect |
| Collector | Strict individual `GET /api/collector/{id}` detail; proven MQTT may supplement displayed state |
| Collections | Discovery/inventory, except existing generic switch reconciliation where specifically implemented |

Gate commands capture an MQTT sequence boundary before REST and require a newer
matching MQTT observation. RFID and collector commands capture their individual
REST generation before REST and require newer matching detail. GRITLock commands
capture and open a new MQTT generation before REST and require its settled
consensus. The LED writes via REST and requires a newer matching full hub
refresh. No current displayed value alone confirms a command.

For GRITLock, exact trigger `/gl` field `gls` is the live lock state. A nonempty,
complete, valid REST `gritLockEnabled` participant set takes precedence and every
required trigger must appear in the fresh generation; non-required observations
do not enter consensus. A complete REST list containing no enabled participant
does not identify a participant set and is therefore unusable for confirmation.
When REST metadata is absent or unusable, participant selection is computed
independently for each fresh quiet-settled generation. If one or more
observations have `gte=1`, exactly those trigger IDs participate and `gte=0`
observations do not enter consensus. If no observation has `gte=1`, all unique
triggers observed in that generation participate, supporting all-zero firmware
behavior. MQTT-derived participants are not persisted into later generations.

A command creates a new generation at its pre-command receive boundary and
invalidates any incomplete active generation, waking the old waiter to fail
closed. The first accepted observation newer than that boundary enters only the
new generation. Natural quiet settlement publishes the authoritative state,
notifies coordinator listeners immediately, stores the bounded result for the
command waiter, and then wakes waiters. Timeout handling never settles active or
partial evidence; it can only consume a result already settled naturally at the
deadline boundary.

All selected observations must agree on `gls`; zero observations,
participant-limit overflow, a missing REST participant, disagreement, stale or
mixed-generation evidence, timeout, disconnect, cancellation, generation
replacement, or an unsettled quiet period remains Unknown or fails
confirmation.

RFID MQTT event refresh is debounced at approximately 250 milliseconds, has at
most one active task and one trailing request per reader, tracks at most 64
readers, and shares a four-request concurrency limit. Gate/RFID reconnect
telemetry requests are similarly bounded and coalesced. Cancellation propagates;
no detached work should continue after unload.

## Privacy boundary

Only strict bounded fields needed for state, availability, entity identity, and
small diagnostics enter coordinator data. Entity attributes use a scalar
allowlist. The integration does not ingest RFID user identity, card details, raw
telemetry, complete MQTT topics, request/response bodies, cookies, or headers.
Config-entry secrets remain in Home Assistant storage and protected backups;
they are not returned by entities or diagnostics.

## Maintainer evidence rule

> Do not assign semantics to a REST field or MQTT payload based on correlation
> alone. Prove both states and both transitions against live evidence before
> changing authority rules.

For a protocol change, first record a redacted evidence matrix with source,
message or endpoint, precondition, action, expected state, observed state, both
transitions, timing, and contradictions. Then encode the smallest authority rule
and reproduce it with deterministic fake REST/MQTT tests. Live evidence never
belongs in test fixtures or the repository.

See [Entities](ENTITIES.md), [Contributing](../CONTRIBUTING.md), or return to the
[README](../README.md).
