# v0.1.1 patch-release checklist

This checklist records the superseded GRITLock `gte=0` compatibility candidate.
`v0.1.1` was not tagged or published; its remaining publication items stay
unchecked and must not be completed.

## Supersession evidence

- [x] All-`gte=0` Lock and Unlock passed on Jeff's installation
- [x] Mixed-`gte` participant regression reproduced on Dion's installation
- [x] PR #25 corrected dual-mode participant selection
- [x] Post-PR #25 command delivery and physical transition succeeded on Dion's installation
- [x] Post-PR #25 confirmation and immediate entity propagation failed on Dion's installation
- [x] v0.1.1 candidate superseded by the v0.1.2 corrective process
- [ ] Corrective v0.1.2 Lock, Unlock, confirmation, and immediate entity state pass on both installations

## Candidate validation

- [ ] Manifest version confirmed as `0.1.1`
- [ ] Full unit suite and CI green
- [ ] HACS validation green
- [ ] Hassfest validation green
- [ ] Changelog and acceptance report finalised
- [ ] Sensitive-value scan clean
- [ ] `git diff --check` clean

## Required live acceptance

- [ ] Clean install on Jeff's system
- [ ] GRITLock Lock succeeds with `gte=0` and `gls=1`
- [ ] GRITLock Unlock succeeds with `gte=0` and `gls=0`
- [ ] No false confirmation toast for Lock or Unlock
- [ ] No regression on the original installation

## Publication

- [ ] Final release commit selected
- [ ] Tag `v0.1.1` created
- [ ] GitHub release created
- [ ] Release notes published
- [ ] Final HACS install completed from published `v0.1.1`

See the [v0.1.1 acceptance report](ACCEPTANCE_REPORT_v0.1.1.md). The published
`v0.1.0` record remains in the
[historical release checklist](RELEASE_CHECKLIST.md).
