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
`/mv-d`, `/p`, `/req-tel`, and `/tel`, plus trigger `/sts` and `/gl`. The defect was not MQTT readiness or entity identity.
Reconciliation issued targeted REST telemetry requests but treated HTTP completion as success, never waited for the
fresh MQTT response, rejected gate `p` when firmware encoded it as numeric text,
and ignored trigger startup `gls` outside `/gl` generations.

PR #28 then made gate startup wait for its bounded requested `/sts` or `/tel`
response, retained RFID's strict individual REST authority, and also required
each GRITLock trigger status to follow its own refresh request. That exact
per-request trigger rule was conservative but depended on a response guarantee
the live backend does not provide.

## Post-PR #28 startup-correlation result

Live testing of exact merged commit `4778958` proved that all gates hydrated,
RFID startup remained correct, and GRITLock alone stayed Unknown and
unavailable. A fresh current-connection capture contained `/sts` for all
relevant GRITLock-capable triggers with unanimous `gls=1`. One later Refresh
All produced only one `/tel`, without `gls`, and did not change state. No
installation identifiers or raw payloads are retained in this report.

The remaining cause was strict causal correlation: the GRITLock session opened
inside the asynchronous request pass and rejected otherwise valid status until
that exact trigger had been marked requested. It then waited for an individual
post-request `gls` that the mesh refresh endpoint does not guarantee.

The correction opens a bounded snapshot synchronously at exact matching-SUBACK
readiness. It accepts strict `/sts` or `/tel` `gls` from that MQTT connection
before, during, or after best-effort refresh completion. `/tel` without `gls`
does not enter the snapshot. Complete REST participant metadata still takes
precedence for startup only; otherwise the quiet-settled set of unique known
triggers that actually reported valid `gls` is the bounded fallback. This
startup source can display state but cannot confirm Lock or Unlock. The first
accepted live `/gl` frame closes any unsettled startup snapshot.

## v0.1.2 observed-state refactor

The architectural audit concluded that displayed state and command confirmation
must not use separate authority structures. The corrective v0.1.2 implementation
retained one latest immutable GRITLock observation containing state, MQTT connection
generation, first and last supporting receive sequence, bounded source, and at
most 64 participant IDs. Startup status and live `/gl` consensus publish through
that same displayed-state field. Command generation IDs, retained generation
results, and command-owned state have been removed.

The continuous live `/gl` evaluator uses only each fresh quiet-settled burst. If
any fresh frame has `gte=1`, exactly that subset participates. If every fresh
frame has `gte=0`, all fresh observed triggers participate, including the sparse
one-frame Unlock pattern captured on Dion's installation and the six-trigger
pattern captured on Jeff's installation. REST participant metadata cannot
mutate or redefine live evidence. Selected disagreement publishes Unknown;
malformed, incomplete, overflowing, or unsettled evidence preserves prior valid
state.

Startup remains a separate bounded evidence source, not a second state field.
Current-connection strict `/sts` or `/tel` `gls` can publish displayed state
through the same observation record. `/tel` without `gls` is ignored. A startup
observation cannot confirm a command, and reconnect rejects old evidence.

## Jeff startup-promotion correction

Live acceptance of exact merged commit `1b5b7e3` confirmed that Dion startup and
both commands passed, while Jeff alone remained Unknown after startup until a
native GRIT app change supplied live `/gl` authority. Jeff's restart capture
contained four unanimous trigger `/sts gls=1` reports and one switch-trigger
`/sts` report without `gls`.

The strict parser already ignored the no-`gls` message, but usable REST
`gritLockEnabled` metadata made the startup collector require every REST-named
participant. If even one named trigger did not report current startup `gls`, the
observed-reporter fallback and its 250 ms quiet wakeup were unreachable, so the
valid unanimous observations expired at the five-second window without
publication. Complete REST sets also used an immediate settlement path instead
of the common quiet boundary.

The corrective startup-only logic keeps an exact complete REST set when all of
its members are represented. When REST metadata is empty, invalid, or not fully
represented, it uses the bounded set of current valid `gls` reporters. Every
valid observation replaces only that trigger's prior value and restarts one
250 ms quiet boundary. Messages without `gls` do not enter the snapshot.
Unanimous or disagreeing evidence publishes through the existing immutable
observed-state channel before the full window expires; no valid reporter remains
Unknown.

The live `/gl` evaluator, pre-REST command boundary, command waiter, explicit
Lock and Unlock mapping, and startup-source confirmation exclusion are unchanged.
The Dion mixed-`gte` Lock and sparse/all-`gte=0` Unlock behavior therefore retain
their existing architecture and deterministic regression coverage.
Lock and Unlock still send explicit desired state to `PUT /api/hub/lockout`.
The entity captures MQTT connection generation and receive sequence before REST,
then waits against the latest observation for a matching naturally settled
`live_gl` result supported entirely by newer receive sequences. The waiter
checks before and after registration, so an observation received while REST is
awaiting is eligible without a lost wakeup. HTTP success, displayed state,
startup status, stale evidence, opposite state, disagreement, disconnect,
reconnect, timeout, and cancellation all fail closed. No-op commands still send
REST and require fresh matching evidence.

Both installations therefore required explicit GRITLock startup, Lock, Unlock,
confirmation, and immediate entity-state retesting before v0.1.2 publication.
Gate and RFID architecture and behavior were not changed by this refactor. The
original boundedness, privacy, cancellation, disconnect, overflow, timeout, and
ordering requirements remain release gates.
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

The corrective implementation, including the Jeff startup-promotion fix, was
validated without API, MQTT, Home Assistant, network, or physical-device access:

- 10 end-to-end GRITLock parser/coordinator/entity pipeline tests passed.
- 27 dedicated startup-hydration tests passed.
- 282 affected coordinator, entity, gate, RFID, collector, MQTT lifecycle,
  startup, and GRITLock command tests passed.
- 11 documentation tests passed.
- 406 complete-suite tests passed, with 1 optional real-Paho smoke test skipped.
- 33 tracked Python files passed compilation and AST parsing.
- 3 tracked JSON files and 7 tracked YAML files parsed successfully.
- `git diff --check` and the sensitive-value scan passed.

Those automated results were later supplemented by successful two-system live
acceptance on exact merged commit
`52d94f64a8ac570f187ffa4428d61a3db7163cf7`.

## Publication state

`v0.1.1` was published on 2026-08-05 and remains a historical, superseded
release. The corrective v0.1.2 release is now prepared at manifest version
`0.1.2` after successful Dion and Jeff live acceptance, but no `v0.1.2` tag or
GitHub release exists yet.

**Acceptance status:** Published v0.1.1 is superseded by the accepted and prepared
v0.1.2 corrective release.

See the [v0.1.2 acceptance report](ACCEPTANCE_REPORT_v0.1.2.md), the
[v0.1.2 release checklist](RELEASE_CHECKLIST_v0.1.2.md), and the
[historical v0.1.0 acceptance report](ACCEPTANCE_REPORT_v0.1.0.md).
