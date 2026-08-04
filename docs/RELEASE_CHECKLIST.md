# v0.1.0 release checklist

Human and external-system tasks remain unchecked unless objective repository
evidence proves completion. Checked owner decisions record approval only; they
do not claim that the transfer, settings, or publication steps occurred.

## Repository decisions

- [x] Organisation display name and intended namespace approved: GoDeeGo Productions / `GoDeeGo-Productions`
- [ ] GitHub organisation and destination repository created or prepared
- [ ] Repository transferred
- [ ] Final repository URL confirmed after transfer
- [ ] Maintainer ownership confirmed
- [ ] Future commit identity policy confirmed
- [x] MIT licence approved and present
- [x] Security reporting channel approved: GitHub Private Vulnerability Reporting
- [ ] GitHub Private Vulnerability Reporting enabled and verified

## Metadata

- [ ] GitHub description set
- [ ] GitHub topics set
- [ ] README URLs checked after transfer
- [ ] manifest URLs checked after transfer
- [ ] hacs.json checked
- [ ] CODEOWNERS checked
- [ ] issue templates checked
- [ ] workflow badges checked

## Quality

- [ ] Full CI green
- [ ] Full unit suite green
- [ ] Secret scan clean
- [ ] Git history exposure reviewed
- [ ] No private OpenAPI content tracked
- [ ] Markdown links valid
- [ ] JSON/YAML valid
- [ ] `git diff --check` clean
- [ ] No repetitive benign MQTT warning noise

## Live acceptance

- [ ] Clean HACS install
- [ ] Initial API authentication
- [ ] MQTT connection and exact subscription
- [ ] Gate startup state
- [ ] Gate HA command
- [ ] Gate GRIT app update
- [ ] Mixed RFID startup states
- [ ] RFID HA lock/unlock
- [ ] RFID GRIT app update responsiveness
- [ ] Offline RFID unavailable
- [ ] GRITLock lock/unlock
- [ ] Collector on/off
- [ ] Collector delayed shutdown
- [ ] LED/other implemented controls
- [ ] Token rotation/Reconfigure
- [ ] No duplicate devices/entities
- [ ] Home Assistant restart
- [ ] Normal uninstall
- [ ] Deterministic clean reinstall

The acceptance report records user-provided live outcomes, but checklist sign-off
remains a separate owner action against the selected immutable release commit.

## Publishing

- [ ] Manifest version confirmed as 0.1.0
- [ ] Changelog finalised
- [ ] Acceptance report signed off
- [ ] Commit selected for release
- [ ] Tag `v0.1.0`
- [ ] GitHub release created
- [ ] Release notes published
- [ ] HACS custom install retested against final organisation URL
- [ ] Official GRIT webpage link published
- [ ] HACS default catalogue submission decision made

See the [acceptance report](ACCEPTANCE_REPORT_v0.1.0.md) and
[repository transfer guide](REPOSITORY_TRANSFER.md).
