# v0.1.1 acceptance report

This report records the published `v0.1.1` patch and the live regressions that
block its corrective `v0.1.2` successor. `v0.1.1` was published on 2026-08-05
and is superseded by the corrective process below.

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

## Post-PR #25 confirmation result

PR #25 corrected that participant-selection defect, but it did not correct the
command-confirmation lifecycle. Subsequent acceptance on Dion's installation
proved that an Unlock REST command was delivered and the physical hub changed
state. A fresh two-trigger generation then reported unanimous `gls=0` with no
`gte=1` observation, yet Home Assistant reported failed confirmation and did not
publish the unlocked entity state.

The remaining defect was the REST precedence boundary: a complete trigger list
with no `gritLockEnabled=true` value was treated as an authoritative empty
participant set. That bypassed the all-`gte=0` MQTT fallback and settled the
fresh generation as Unknown. The timeout path also attempted settlement, which
was inconsistent with the required natural quiet boundary. The v0.1.2
correction treats an empty REST set as unusable, replaces stale command
generations, and permits only natural quiet settlement to publish state.

## Post-PR #26 state-pipeline result

Live testing of the exact merged PR #26 build proved that the bounded command
generation fix did not resolve the end-to-end state pipeline. REST delivery and
physical changes worked, but startup and post-command Home Assistant state could
be wrong or become Unknown.

The corrective audit found no inversion in raw parsing: `gls=1` remained locked
`True` and `gls=0` remained unlocked `False`. The coordinator instead conflated
the newest settled generation result with persistent authoritative state, so a
later incomplete generation could replace a valid `False` or `True` with
`None`. It also exposed unproven REST `gritLockState` as provisional state.

The v0.1.2 correction keeps the last valid settled MQTT boolean through REST
polls, failed commands, timeouts, incomplete generations, and overflow. A
complete selected-participant disagreement explicitly invalidates authority,
and disconnect clears MQTT authority. With no valid MQTT state the entity is
Unknown and unavailable; exact `False` remains a valid unlocked state.

## Post-state-pipeline startup result

Live testing of exact merged main commit `9cd5807` proved that RFID readers
hydrated successfully while gates and GRITLock remained Unknown after startup.
A bounded broad-topic diagnostic established the relevant message families
without retaining installation identifiers or payloads: gate `/sts`, `/mv`,
`/mv-d`, `/p`, `/req-tel`, and `/tel`, plus trigger `/sts` and `/gl`. The
defect was not
MQTT readiness or entity identity. Reconciliation issued targeted REST
telemetry requests but treated HTTP completion as success, never waited for the
fresh MQTT response, rejected gate `p` when firmware encoded it as numeric text,
and ignored trigger startup `gls` outside `/gl` generations.

The corrective startup pass now begins only after exact matching SUBACK
readiness. It sends bounded authenticated per-target telemetry requests, waits
for fresh requested `/sts` or `/tel`, and treats `/req-tel` only as a request
marker. Gate state enters the established per-device MQTT path. A complete
unanimous trigger startup set hydrates GRITLock authority without entering or
confirming a `/gl` command generation. RFID remains authoritative from strict
individual REST detail. Missing or invalid responses fail closed per target and
do not erase state accepted for another device.

## Corrective process

The published v0.1.1 release is superseded by the v0.1.2 corrective
process. The safe per-generation fallback is:

1. Use a nonempty, complete, valid REST `gritLockEnabled` participant set when available.
2. Otherwise, after quiet settlement, use exactly the fresh `gte=1` trigger IDs
   if that subset is nonempty.
3. If no fresh observation has `gte=1`, use all unique triggers observed in that
   fresh generation.
4. Never persist MQTT-derived participant IDs into an unrelated generation.

Both installations require explicit Lock and Unlock retesting of the corrected
command-confirmation and immediate entity-state path before v0.1.2 publication.
The original fail-closed bounds, ordering, cancellation, disconnect, overflow,
timeout, and stale-generation requirements remain release gates.

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

## Current corrective automated validation

The v0.1.2 state-pipeline and startup-hydration corrections were validated
without API, MQTT, Home Assistant, or physical-device access:

- 287 focused API, MQTT lifecycle/readiness, runtime ordering, coordinator, gate,
  RFID, GRITLock, and startup-hydration regression tests passed.
- 10 dedicated startup-hydration tests passed.
- 11 documentation tests passed.
- 394 complete-suite tests passed, with 1 optional real-Paho smoke test skipped.
- 33 Python files compiled in memory and parsed as AST.
- 3 JSON files and 7 YAML files parsed successfully.
- `git diff --check` and the changed-file sensitive-value scan passed.

These automated results do not replace the required Lock and Unlock acceptance
on both live systems.
## Publication state

`v0.1.1` was published on 2026-08-05 and is the latest published release. The
manifest remains at `0.1.1`; no `v0.1.2` tag, release, or publication is claimed.
The corrective patch remains blocked until both systems pass live startup,
Lock, Unlock, confirmation, and immediate-state acceptance.

**Acceptance status:** Published v0.1.1 is superseded; v0.1.2 remains blocked
pending live acceptance on Dion's and Jeff's installations.

See the [v0.1.1 release checklist](RELEASE_CHECKLIST_v0.1.1.md) and the
[historical v0.1.0 acceptance report](ACCEPTANCE_REPORT_v0.1.0.md).
