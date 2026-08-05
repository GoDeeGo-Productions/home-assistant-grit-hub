# v0.1.1 acceptance report

This report covers the `v0.1.1` patch release candidate. It does not claim that
`v0.1.1` has been tagged or published.

## Scope

The patch is limited to GRITLock compatibility with trigger `/gl` MQTT messages
whose advisory `gte` field is `0`. It does not change API authentication,
commands, entity identity, polling, configuration, or other device behavior.

`gls` remains the authoritative live lock state. A complete, valid REST
`gritLockEnabled` participant set takes precedence. When that metadata is absent
or unusable, the exact bounded set of unique triggers observed in the fresh
quiet-settled `/gl` generation defines the participants. `gte` is strictly
validated but advisory only. Empty, incomplete, contradictory, stale,
overflowing, timed-out, and unsettled generations fail closed.

## Automated validation

Release-preparation validation on 2026-08-05 produced these network-free totals:

- 10 focused documentation tests passed.
- 4 focused manifest compatibility tests passed.
- 362 complete-suite tests passed, with 1 optional real-Paho smoke test skipped.
- 31 Python files compiled in memory and parsed as AST.
- 3 JSON files and 7 YAML files parsed successfully.
- `git diff --check` passed.
- The added-line sensitive-value scan found no credential, private-address,
  private-key, live-identifier, or credential-bearing URL values.

Official HACS and Hassfest validation remains a CI release gate; local
HACS/Hassfest-compatible manifest and repository tests passed.

## Required live verification

Before publication, perform an explicitly authorised live verification on
Jeff's installation and record all of the following:

- GRITLock **Lock** completes with retained/current trigger observations showing
  `gte=0` and `gls=1`.
- GRITLock **Unlock** completes with retained/current trigger observations
  showing `gte=0` and `gls=0`.
- Neither command produces a false confirmation-failure toast.
- Startup state, external GRITLock changes, reconnect behavior, and the original
  installation show no regression.
- A clean HACS installation of the candidate succeeds.

This release-preparation task performs no live verification and contacts no API,
MQTT broker, Home Assistant instance, network host, or physical equipment.

## Publication state

`v0.1.0` remains the latest published release. The `v0.1.1` tag, GitHub release,
release notes, and final HACS installation from the published artifact remain
pending.

**Acceptance status:** Conditionally accepted as v0.1.1 release candidate,
subject to live verification and publication steps.

See the [v0.1.1 release checklist](RELEASE_CHECKLIST_v0.1.1.md) and the
[historical v0.1.0 acceptance report](ACCEPTANCE_REPORT_v0.1.0.md).
