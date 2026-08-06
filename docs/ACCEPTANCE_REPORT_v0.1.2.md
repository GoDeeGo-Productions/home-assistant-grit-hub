# v0.1.2 acceptance report

## Acceptance status

v0.1.2 is accepted and prepared for publication after successful two-system live
acceptance. Publication mechanics remain outstanding: no `v0.1.2` tag or GitHub
release exists yet.

## Accepted source

The accepted implementation is exact merged main commit:

`52d94f64a8ac570f187ffa4428d61a3db7163cf7`

The manifest is prepared at version `0.1.2`. This patch release is limited to the
corrective GRITLock state, confirmation, compatibility, and startup work already
merged in that commit. It adds no new feature or device-command behavior.

## Dion installation acceptance

The Dion installation passed on the exact accepted commit:

- GRITLock startup state was correct and the entity was available.
- Locked and Unlocked states exposed the correct Home Assistant action.
- Home Assistant Lock physically worked, confirmed without error, and updated
  displayed state and action.
- Home Assistant Unlock physically worked, confirmed without error, and updated
  displayed state and action.
- Gate startup hydration remained correct.
- RFID startup/detail authority remained correct.

This acceptance covers the mixed `gte=1` Lock pattern and the sparse/all-`gte=0`
Unlock pattern.

## Jeff installation acceptance

The Jeff installation passed on the same exact accepted commit:

- GRITLock startup state was correct and the entity was available.
- The displayed Home Assistant action was correct.
- Home Assistant Lock and Unlock both worked without confirmation errors.
- Gates and the other integration entities remained correct.

This acceptance covers Jeff-style startup promotion and the all-`gte=0` Lock and
Unlock pattern.

## Corrective release behavior

v0.1.2 uses one continuous immutable GRITLock observed-state channel. Lock and
Unlock remain explicit REST desired-state commands, and confirmation requires a
fresh matching post-command `/gl` observation on that same authority. Startup
status can establish displayed state but cannot confirm a command.

Incomplete evidence and command timeout preserve the prior valid observation.
Complete selected-participant disagreement and MQTT disconnect invalidate
GRITLock authority. Gate startup hydration and RFID startup/detail authority are
unchanged.

## Separate follow-up

An occasional missed individual downstream trigger after a hub-level Lock or
Unlock is a separate propagation-reliability issue. It is outside v0.1.2 scope
and is not claimed as fixed or included in this acceptance decision.

## Automated and repository validation

Release-candidate validation recorded:

- 406 unit tests passed.
- 1 optional real-Paho smoke test was skipped as expected.
- HACS validation passed for the integration repository.
- Hassfest validation passed for the Home Assistant custom integration.
- Python AST parsing and in-memory compilation passed.
- Tracked JSON and YAML syntax validation passed.
- Manifest and release-document consistency checks passed with version `0.1.2`.
- `git diff --check` passed.
- The sensitive-value scan found no embedded installation secret or private
  installation value.

All automated testing was network-free and used fabricated identifiers. It did
not contact a GRIT API, MQTT broker, Home Assistant instance, or physical
equipment.

## Publication state

v0.1.2 is prepared for publication but is not yet published. No release tag has
been created or pushed, and no GitHub release or post-release HACS verification
is claimed.

**Final status:** Accepted for v0.1.2 publication, subject only to the release
commit, tag, GitHub release, and post-release verification steps in the
[v0.1.2 release checklist](RELEASE_CHECKLIST_v0.1.2.md).
