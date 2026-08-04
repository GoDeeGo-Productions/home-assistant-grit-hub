# Contributing

Focused, reviewable contributions are welcome. Preserve proven behavior unless a
change has explicit evidence and scope. GRIT equipment controls physical access,
so correctness, privacy, bounded work, and fail-closed confirmation take priority
over convenience.

## Development setup

1. Fork or clone the repository into a dedicated GRIT workspace.
2. Create a focused `codex/*` or descriptive feature branch.
3. Use a supported Python version for the standard-library tests. Home Assistant
   development dependencies are not required for the isolated suite.
4. Do not copy Home Assistant `.storage`, databases, backups, diagnostics, logs,
   or private API references into the repository.
5. Do not install or contact a broker merely to run unit tests.

Run the network-free suite:

```text
python -m unittest discover -s tests -p "test_*.py"
```

Compile all Python files and check whitespace:

```text
python -m compileall -q custom_components scripts tests
git diff --check
```

Also parse all JSON and YAML using the available local validation tools and run
HACS/Hassfest through CI after an authorized push. Do not ignore validator checks
to force a pass.

## Test data and network safety

Tests must use deterministic fake REST sessions and fake Paho clients. They must
not create sockets, threads owned by Paho, MQTT publications, live API requests,
or physical commands. Use fabricated `.invalid` hosts, documentation-only
addresses, fabricated IDs, and non-secret token shapes. Bounded events and join
or wait timeouts must fail tests instead of hanging; avoid arbitrary sleeps.

Never include real credentials, bearer headers, cookies, private addresses,
hostnames, hub/device IDs, customer information, RFID user/card data, raw API
responses, MQTT payloads, logs, or diagnostic captures.

## State authority and commands

Current authority is intentionally device-specific:

- gate: MQTT live state;
- RFID: individual REST detail, with MQTT `s`/`st` invalidation only;
- GRITLock: settled trigger `/gl` MQTT consensus with provisional strict REST
  startup fields;
- collector: individual REST detail;
- collections: discovery/inventory unless a specific existing path says
  otherwise.

Do not publish optimistic command state. Capture the relevant sequence or
generation before the REST command and require strictly newer matching evidence.
HTTP success and current displayed state alone are not confirmation. Preserve
bounded concurrency, coalescing, timeout, cancellation, disconnect, and unload
cleanup.

> Do not assign semantics to a REST field or MQTT payload based on correlation
> alone. Prove both states and both transitions against live evidence before
> changing authority rules.

## Protocol-change evidence

Before changing a state mapping, endpoint, message type, or source authority,
prepare a private redacted matrix. Record exact message types and endpoint paths,
but replace all identifiers and omit every secret and payload field not needed
for the proof.

| Case | REST evidence | MQTT evidence | Physical result |
| --- | --- | --- | --- |
| Startup state A | | | |
| Startup state B | | | |
| Command A→B | | | |
| Command B→A | | | |
| Offline | | | |

Evidence must distinguish observation from inference, cover contradictions and
timing, and be translated into the smallest deterministic regression test. Do
not commit the live evidence matrix or installation capture.

## Privacy and logging

Retain only bounded allowlisted state needed by entities. Never log or return
credentials, headers, cookies, request bodies, response bodies, complete MQTT
topics, broker/API addresses, hub/device IDs, personal data, or raw payloads.
Errors should contain a generic category, method, bounded endpoint identifier,
and status only where necessary. Valid unsupported input should be debug or
silent; malformed input may be a generic warning.

## Pull requests

A pull request should:

- explain the concrete problem and narrow behavior change;
- identify any physical-operation or privacy risk;
- list exact files and authority rules affected;
- include deterministic production-behavior regression tests;
- report local compilation, JSON/YAML, unit, diff, and sensitive-value checks;
- state that no live equipment was contacted by automated tests;
- update documentation/localization only where behavior changed;
- avoid unrelated formatting, redesign, generated artifacts, and private data.

Do not push, merge, release, or change repository settings without the required
owner authorization. Read [Architecture](docs/ARCHITECTURE.md) and
[Security](SECURITY.md) before changing runtime code.
