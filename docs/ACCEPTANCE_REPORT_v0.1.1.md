# v0.1.1 acceptance report

This report records the superseded `v0.1.1` patch release candidate. `v0.1.1`
was not tagged or published.

## Scope

The candidate attempted to make GRITLock compatible with trigger `/gl` MQTT
messages whose `gte` field was `0`. It did not change API authentication,
commands, entity identity, polling, configuration, or other device behavior.

`gls` remained the authoritative live lock state and complete, valid REST
`gritLockEnabled` participant metadata retained precedence. When REST metadata
was unavailable, however, the v0.1.1 candidate treated every fresh observation
as a participant and did not preserve the fresh generation's `gte=1` selector
semantics.

## Two-system live result

User-provided live acceptance evidence established two valid deployment
patterns without recording any address, credential, identifier, or raw payload:

- Jeff's installation passed Lock and Unlock with all six fresh triggers
  reporting `gte=0`, using unanimous `gls=1` and `gls=0` respectively.
- Dion's installation exposed a regression. Its mixed Lock generation contained
  seven `gte=1` participants plus two `gte=0` nonparticipants. A later Unlock
  generation contained only the two `gte=0` triggers. Treating every observation
  in the mixed generation as a participant was incompatible with this system's
  explicit-selector behavior.

The all-zero result proves that `gte=0` is not a universal exclusion rule. The
mixed result proves that, when any fresh observation has `gte=1`, the exact
fresh `gte=1` subset must define MQTT fallback participants.

## Corrective process

The v0.1.1 candidate is superseded by the v0.1.2 corrective process. The safe
per-generation fallback is:

1. Use a complete, valid REST `gritLockEnabled` participant set when available.
2. Otherwise, after quiet settlement, use exactly the fresh `gte=1` trigger IDs
   if that subset is nonempty.
3. If no fresh observation has `gte=1`, use all unique triggers observed in that
   fresh generation.
4. Never persist MQTT-derived participant IDs into an unrelated generation.

Both installations require explicit Lock and Unlock retesting before v0.1.2
publication. The original fail-closed bounds, ordering, cancellation, disconnect,
overflow, timeout, and stale-generation requirements remain release gates.

## Original automated validation

The v0.1.1 release-preparation validation on 2026-08-05 was network-free:

- 10 focused documentation tests passed.
- 4 focused manifest compatibility tests passed.
- 362 complete-suite tests passed, with 1 optional real-Paho smoke test skipped.
- 31 Python files compiled in memory and parsed as AST.
- 3 JSON files and 7 YAML files parsed successfully.
- `git diff --check` and the added-line sensitive-value scan passed.

Those results did not encode the later two-system mixed-generation evidence and
do not make the superseded candidate acceptable for publication.

## Publication state

`v0.1.0` remains the latest published release. No `v0.1.1` tag, GitHub release,
or published HACS artifact is claimed by this report. The manifest remains at
`0.1.1` until the formal v0.1.2 release-preparation process occurs after both
systems pass.

**Acceptance status:** Superseded by the v0.1.2 corrective patch process;
`v0.1.1` is not accepted for publication.

See the [v0.1.1 release checklist](RELEASE_CHECKLIST_v0.1.1.md) and the
[historical v0.1.0 acceptance report](ACCEPTANCE_REPORT_v0.1.0.md).
