# v0.1.0 release checklist

Human and external-system tasks remain unchecked unless objective evidence
proves completion. Checked items record approved decisions and verified transfer,
acceptance, or publication facts; unchecked items remain unresolved.

## Repository decisions

- [x] Organisation display name and namespace verified: GoDeeGo Productions / `GoDeeGo-Productions`
- [x] GitHub organisation and destination repository created
- [x] Repository transferred
- [x] Final repository URL confirmed after transfer
- [x] Local Git remote updated to the final repository URL
- [ ] Maintainer ownership confirmed
- [ ] Future commit identity policy confirmed
- [x] MIT licence approved and present
- [x] Security reporting channel approved: GitHub Private Vulnerability Reporting
- [x] GitHub Private Vulnerability Reporting enabled and verified
- [x] Dependency graph enabled
- [x] Dependabot alerts enabled

## Metadata

- [x] GitHub description set
- [x] GitHub topics set
- [x] README URLs checked after transfer
- [x] manifest URLs checked after transfer
- [x] hacs.json checked
- [ ] CODEOWNERS checked
- [x] issue templates checked
- [x] workflow badge decision checked; none included for v0.1.0

## Quality

- [x] Full CI green
- [x] Full unit suite green
- [x] Secret scan clean
- [x] Git history exposure reviewed
- [x] No private OpenAPI content tracked
- [x] Markdown links valid
- [x] JSON/YAML valid
- [x] `git diff --check` clean
- [x] No repetitive benign MQTT warning noise

## Live acceptance

- [x] Clean HACS install
- [x] Initial API authentication
- [x] MQTT connection and exact subscription
- [x] Gate startup state
- [x] Gate HA command
- [x] Gate GRIT app update
- [x] Mixed RFID startup states
- [x] RFID HA lock/unlock
- [x] RFID GRIT app update responsiveness
- [x] Offline RFID unavailable
- [x] GRITLock lock/unlock
- [x] Collector on/off
- [x] Collector delayed shutdown
- [x] LED/other implemented controls
- [x] Token rotation/Reconfigure
- [x] No duplicate devices/entities
- [x] Home Assistant restart
- [x] Normal uninstall
- [x] Deterministic clean reinstall

The acceptance report records the signed-off live outcomes from the transferred
repository URL. Release `v0.1.0` was published from the immutable commit recorded
below; the unchecked governance and future-distribution items remain separate.

## Publishing

- [x] Manifest version confirmed as 0.1.0
- [x] Changelog finalised
- [x] Acceptance report signed off
- [x] Final release commit selected: `9464dbab1798cae3b2d0f538d0db3ed64d510884`
- [x] Tag `v0.1.0`
- [x] GitHub release created: [GRIT Hub for Home Assistant v0.1.0](https://github.com/GoDeeGo-Productions/home-assistant-grit-hub/releases/tag/v0.1.0)
- [x] Release notes published
- [x] HACS custom install retested against final organisation URL
- [ ] Official GRIT webpage link published
- [ ] HACS default catalogue submission decision made

See the [acceptance report](ACCEPTANCE_REPORT_v0.1.0.md) and
[repository transfer guide](REPOSITORY_TRANSFER.md).
