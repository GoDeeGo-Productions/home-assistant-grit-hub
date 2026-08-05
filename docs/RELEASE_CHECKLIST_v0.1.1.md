# v0.1.1 patch-release checklist

This checklist records the published but superseded GRITLock `gte=0`
compatibility patch and the remaining v0.1.2 corrective gates. `v0.1.1` was
published on 2026-08-05; v0.1.2 is not tagged or published.

## Supersession evidence

- [x] All-`gte=0` Lock and Unlock passed on Jeff's installation
- [x] Mixed-`gte` participant regression reproduced on Dion's installation
- [x] PR #25 corrected dual-mode participant selection
- [x] Post-PR #25 command delivery and physical transition succeeded on Dion's installation
- [x] Post-PR #25 confirmation and immediate entity propagation failed on Dion's installation
- [x] PR #26 corrected command-generation settlement
- [x] Exact merged PR #26 build reproduced wrong startup and post-command state on Dion's installation
- [x] End-to-end state-pipeline cause identified and corrected offline
- [x] Exact merged `9cd5807` build reproduced Unknown gate and GRITLock startup while RFID hydrated
- [x] Startup response families and ordering audited without retaining installation data
- [x] Bounded post-SUBACK request/response hydration implemented and tested offline
- [ ] Corrective v0.1.2 Lock, Unlock, confirmation, and immediate entity state pass on both installations

## Corrective validation

- [x] Manifest remains `0.1.1`
- [x] Complete local unit suite green
- [ ] HACS validation green for the corrective branch
- [ ] Hassfest validation green for the corrective branch
- [x] Changelog, architecture, entity, troubleshooting, and acceptance documentation updated
- [x] Sensitive-value scan clean
- [x] `git diff --check` clean

## Required v0.1.2 live acceptance

- [ ] Clean corrected build installed on Jeff's system
- [ ] Jeff gate startup state hydrates from fresh requested MQTT status
- [ ] Jeff GRITLock startup state hydrates from fresh requested trigger status
- [ ] Jeff GRITLock Lock succeeds with all-`gte=0`, `gls=1`
- [ ] Jeff GRITLock Unlock succeeds with all-`gte=0`, `gls=0`
- [ ] Clean corrected build installed on Dion's system
- [ ] Dion gate startup state hydrates for every responding gate
- [ ] Dion startup all-`gte=0`, `gls=0` displays Unlocked and offers Lock
- [ ] Dion mixed `gte=1`, `gls=1` generation displays Locked and offers Unlock
- [ ] Dion fresh all-`gte=0`, `gls=0` Unlock confirms and displays Unlocked
- [ ] No false confirmation toast for Lock or Unlock
- [ ] Partial or missing startup responses leave only affected devices Unknown
- [ ] No regression on gate, RFID, collector, LED, config flow, or MQTT lifecycle

## Publication history and next release

- [x] v0.1.1 tag and release recorded as published on 2026-08-05
- [x] v0.1.1 release notes published
- [ ] Final v0.1.2 release commit selected
- [ ] Tag `v0.1.2` created
- [ ] GitHub release v0.1.2 created
- [ ] v0.1.2 release notes published
- [ ] Final HACS install completed from published `v0.1.2`

See the [v0.1.1 acceptance report](ACCEPTANCE_REPORT_v0.1.1.md). The original
[v0.1.0 release checklist](RELEASE_CHECKLIST.md) remains historical evidence.
