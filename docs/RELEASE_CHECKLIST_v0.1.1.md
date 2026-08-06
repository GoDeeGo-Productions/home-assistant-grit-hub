# v0.1.1 patch-release checklist

This checklist records the published but superseded GRITLock `gte=0`
compatibility patch and the historical v0.1.2 corrective handoff. `v0.1.1` was
published on 2026-08-05; v0.1.2 is prepared after successful acceptance but is
not tagged or published.

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
- [x] Exact merged PR #28 passed gate and RFID startup on Dion's installation
- [x] Exact merged PR #28 left GRITLock Unknown despite unanimous current-connection `/sts gls=1`
- [x] Strict per-request GRITLock startup correlation defect identified and corrected offline
- [x] Command-generation architecture independently audited and rejected
- [x] One continuous immutable GRITLock observed-state channel implemented offline
- [x] Command generation IDs and retained command-result map removed
- [x] Sparse one-frame all-`gte=0` Unlock and six-trigger all-`gte=0` behavior covered by deterministic tests
- [x] Pre-REST connection/sequence boundary and lost-wakeup-safe waiting covered by deterministic tests
- [x] Exact merged `1b5b7e3` passed Dion startup, Lock, Unlock, confirmation, gates, and RFID
- [x] Exact merged `1b5b7e3` reproduced Jeff-only Unknown startup until the first native `/gl` change
- [x] Jeff restart evidence reduced to four unanimous `/sts gls=1` reporters plus one no-`gls` switch message
- [x] REST-set incompleteness, unreachable fallback, and disabled quiet wakeup identified as the startup cause
- [x] Bounded observed-reporter startup fallback and common 250 ms quiet settlement implemented offline
- [x] Deterministic Jeff Locked/Unlocked startup and Dion startup/command regressions added
- [x] Exact merged `52d94f6` passed final GRITLock startup, Lock, Unlock, confirmation, gate, and RFID acceptance on both installations

## Corrective validation

- [x] Historical v0.1.1 release manifest was `0.1.1`
- [x] Complete local unit suite green
- [x] HACS validation green
- [x] Hassfest validation green
- [x] Changelog, architecture, entity, troubleshooting, and acceptance documentation updated
- [x] Sensitive-value scan clean
- [x] `git diff --check` clean

## v0.1.2 acceptance handoff

- [x] Exact merged commit `52d94f64a8ac570f187ffa4428d61a3db7163cf7` accepted
- [x] Dion GRITLock startup, Lock, Unlock, confirmation, gates, and RFID passed
- [x] Jeff GRITLock startup, Lock, Unlock, confirmation, gates, and other entities passed
- [x] No confirmation errors observed during final two-system acceptance
- [x] Separate downstream-trigger propagation issue excluded from v0.1.2 scope

See the [v0.1.2 acceptance report](ACCEPTANCE_REPORT_v0.1.2.md) and
[v0.1.2 release checklist](RELEASE_CHECKLIST_v0.1.2.md) for the final accepted
evidence and remaining publication mechanics.

## Publication history

- [x] v0.1.1 tag and release recorded as published on 2026-08-05
- [x] v0.1.1 release notes published
- [x] v0.1.1 recorded as superseded by the prepared v0.1.2 corrective release
- [ ] v0.1.2 tag and GitHub release remain pending in the separate v0.1.2 checklist

The original [v0.1.0 release checklist](RELEASE_CHECKLIST.md) remains historical
evidence.
