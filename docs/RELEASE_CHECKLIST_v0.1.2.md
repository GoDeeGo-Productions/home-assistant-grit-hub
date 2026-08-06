# v0.1.2 release checklist

This checklist separates completed code and live acceptance from the remaining
publication mechanics. v0.1.2 is prepared but is not yet tagged or published.

## Accepted baseline and scope

- [x] Exact accepted main commit recorded: `52d94f64a8ac570f187ffa4428d61a3db7163cf7`
- [x] Corrective scope limited to GRITLock compatibility, observed state,
  confirmation, and startup hydration
- [x] Dion live acceptance results recorded
- [x] Jeff live acceptance results recorded
- [x] Gate startup hydration preservation accepted
- [x] RFID startup/detail authority preservation accepted
- [x] Individual downstream-trigger propagation reliability kept as a separate
  follow-up issue

## Release-candidate validation

- [x] Manifest version is exactly `0.1.2`
- [ ] Working tree clean at the final release commit
- [x] Full unit suite green: 406 passed, 1 expected optional real-Paho skip
- [x] HACS validation passed
- [x] Hassfest validation passed
- [x] Static Python, JSON, and YAML validation passed
- [x] Release documentation and relative Markdown links validated
- [x] Sensitive-value scan clean
- [x] `git diff --check` clean
- [x] v0.1.2 changelog and release notes drafted
- [ ] Final release commit selected and verified

## Publication

- [ ] Annotated or signed `v0.1.2` tag created from the selected release commit
- [ ] `v0.1.2` tag pushed to the configured origin
- [ ] GitHub release `v0.1.2` created
- [ ] Release notes published
- [ ] Post-release HACS Custom Repository install/update verified from `v0.1.2`
- [ ] Final corrective issue closeout completed

No publication checkbox may be marked complete solely because the release
candidate passed validation. See the
[v0.1.2 acceptance report](ACCEPTANCE_REPORT_v0.1.2.md) for accepted evidence
and scope.
