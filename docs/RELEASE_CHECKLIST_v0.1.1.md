# v0.1.1 patch-release checklist

This checklist tracks the GRITLock `gte=0` compatibility patch. Items remain
unchecked until their release evidence is reviewed; `v0.1.1` is not yet tagged
or published.

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
