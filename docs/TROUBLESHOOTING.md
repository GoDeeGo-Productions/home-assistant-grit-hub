# Troubleshooting

Begin with passive checks. Do not repeatedly operate access-control equipment to
diagnose a software problem. Replace every placeholder below and never post the
result if it contains a secret or installation identifier.

## Integration does not appear

Confirm the installed path is exactly
`/config/custom_components/grit_hub/manifest.json`, restart Home Assistant, and
refresh the browser. Home Assistant `2026.3.0` or newer is required. For HACS,
confirm the repository was added as category **Integration**, not Plugin.

## API URL or authentication fails

- Enter the API base URL, not a browser login or redirect URL.
- Enter the raw token only. Do not include `Bearer `, quotes, leading/trailing
  spaces, or an `auth_token` query parameter.
- The token is opaque and may be long. The integration rejects only blank,
  unbounded, control-character, or header-unsafe input locally; the bounded
  authenticated `GET /api/hub` determines acceptance.
- An actual HTTP 401 maps to `invalid_auth`. A timeout, DNS, TLS, or transport
  failure maps to a connection error without exposing response content.
- Keep certificate verification enabled unless a controlled diagnostic has
  separately verified the endpoint.

The optional offline diagnostic uses exactly the production token normalization
and authorization header and refuses redirects:

```text
python scripts/diagnose_hub_response.py --base-url "https://your-grit-server.example"
```

The script prompts for the token with hidden input, so it is not placed in the
command line. Do not paste its shell history or output into an issue until all
secrets and site identifiers are removed.

## Setup asks for a broker address

This means authenticated `/api/hub` returned a valid hub ID but no usable LAN
address. Enter only the GRIT Hub LAN hostname or IP address. The flow retains the
hub ID and defaults; it does not scan the network or ask for the ID again.

## `mqtt_cannot_connect`

Check broker reachability, port, listener protocol, username/password, topic hub
ID, TLS mode, and certificate trust. The error deliberately does not disclose
whether an installation-specific endpoint, credential, or identifier was
accepted. Readiness requires connection plus the exact matching successful
SUBACK; a connection alone is insufficient.

With explicit authorization for a passive live diagnostic, a trusted local
shell, and placeholders replaced locally, the equivalent subscription shape is:

```text
mosquitto_sub -h "<broker-host>" -p "<broker-port>" -u "<mqtt-username>" -P "<mqtt-password>" -t "grit/<hub-id>/+/+/#" -q 0 -C 1 -W 15
```

This command never publishes, but its password argument can remain in local shell
history or process listings. Prefer a protected client configuration supported
by your Mosquitto installation and never copy the real command into a report.
Do not run it without authorization to contact the broker.

## Entry remains not ready

Both the initial REST refresh and MQTT readiness must succeed. Home Assistant
will retry setup rather than load a partial runtime. Check the API and broker
paths independently; do not disable TLS verification as a permanent workaround.

## Gate is Unknown or does not confirm

Gate state requires authoritative MQTT. Confirm the MQTT Connection diagnostic
is on. After the exact subscription is ready, the integration makes a bounded
authenticated telemetry request and waits for a fresh gate `/sts` or `/tel`
response; it does not depend on a retained message. `/req-tel` only shows that a
request reached the device and cannot set state. REST polling cannot invent a
gate state. A Home Assistant command succeeds only after a matching observation
newer than the pre-command sequence; pre-command, contradictory, missing, or
disconnected evidence fails closed. One missing gate response does not erase
valid state already accepted for another gate.

If physical movement occurred but the service reports no confirmation, stop
repeating the command and collect only redacted logs. Treat the physical site as
a separate safety concern.

## RFID state is stale, Unknown, or unavailable

RFID state comes only from strict individual `GET /api/rfid/{id}` detail.
Collection `lockout`, MQTT `sts.s`, and MQTT `s`/`st` payload values are not lock
state. Exact `s` and `st` messages only trigger a bounded individual refresh.
An offline reader is unavailable; temporary read failures retain the last valid
state rather than inventing one. The default poll is a 30-second fallback.

## GRITLock is Unknown or does not confirm

GRITLock has one continuous observed-state channel. Exact `gls=1` is Locked,
`gls=0` is Unlocked, and zero is not treated as missing. At startup or reconnect,
a bounded current-connection snapshot accepts strict trigger `/sts` or `/tel`
`gls`; trigger messages without `gls` are ignored and cannot block hydration.
A complete REST participant set is exact only when fully represented by current
`gls`. Otherwise, bounded observed reporters are evaluated after 250 ms quiet
instead of waiting for the full five-second window. Startup status can display
state but cannot confirm a later command.

Live `/gl` bursts choose participants only from their fresh frames. A mixed
burst uses exactly the fresh `gte=1` subset. An all-`gte=0` burst uses all fresh
observed triggers, including one sparse valid frame. REST participant metadata
may bound startup hydration but cannot redefine live evidence. Selected
participants must agree on `gls`; complete disagreement makes the entity Unknown.
Malformed, incomplete, overflowing, timed-out, or unsettled live evidence
preserves an earlier valid state and publishes no new authority.

Lock and Unlock capture MQTT connection and receive-sequence boundaries before
the explicit REST request. Confirmation needs a naturally settled matching
`live_gl` observation whose supporting frames are all newer than that boundary.
HTTP success, the displayed state, startup status, stale evidence, an opposite
state, timeout, disconnect, or reconnect cannot confirm. A frame arriving while
the REST request is still awaiting remains eligible. No-op requests also require
fresh evidence; there are no command generation IDs or retained result map.

If physical equipment changes but Home Assistant reports failed confirmation,
do not repeat the command. Verify the site safely and retain only redacted logs.
For v0.1.2, GRITLock startup, Lock, Unlock, confirmation, and immediate state
remain blocked pending live acceptance on Dion's and Jeff's systems. Gate and
RFID behavior was not changed by this refactor and must remain green during that
acceptance.

## Collector command waits or fails

A collector can legitimately remain in a transition during delayed shutdown.
Confirmation polls its individual detail within fixed bounds and accepts only a
newer, online, settled matching state. Do not assume collection data or HTTP
success confirms the final state. If it times out, inspect the device safely
before retrying.

## Missing or duplicate entities

New devices may require an integration reload because dynamic entity discovery
is not implemented. Reconfigure updates the existing entry and should preserve
identities. If upgrading an early development build, an obsolete RFID switch may
remain in the entity registry; remove only that orphan through Home Assistant's
UI after confirming the RFID lock exists. Never edit `.storage` manually.

## Restart or uninstall problems

Follow [Installation](INSTALLATION.md). For a normal uninstall, remove the config
entry, remove the integration through HACS or its manual directory, and restart.
For deterministic development cleanup, follow the documented stop/remove/verify
order and remove only `/config/custom_components/grit_hub`.

## Safe log redaction

Make a copy of the log and run the repository's bounded redactor to a different
output path:

```text
python scripts/redact_grit_log.py --input "<path-to-log-copy>" --output "<path-to-redacted-log>"
```

The script refuses same-file output and files over its input bound. It redacts
Bearer headers, common GRIT-token shapes, IPv4 addresses, and email addresses.
It cannot prove a log is safe: manually review the result for hostnames, IPv6,
hub/device IDs, customer names, MQTT topics, payloads, cookies, subscription
codes, and any installation-specific values before sharing.

Malformed MQTT input remains a generic warning. A valid JSON object containing
no supported allowlisted fields is ignored at debug level to avoid repetitive
benign warning noise. Neither case should log payloads, complete topics, broker
addresses, hub/device IDs, or credentials.

Return to the [README](../README.md) or review [Security](../SECURITY.md).
