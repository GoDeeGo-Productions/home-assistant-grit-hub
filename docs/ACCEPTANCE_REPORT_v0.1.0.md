# v0.1.0 acceptance report

This is an engineering acceptance record, not marketing. It separates
user-provided live hardware evidence, repository-derived behavior, automated
offline evidence, and owner decisions.

## 1. Scope

The candidate covers the existing GRIT Hub Home Assistant integration: HACS
custom-repository packaging, authenticated REST discovery, subscribe-only MQTT
readiness, documented entities, bounded reconciliation and confirmation,
reconfiguration, privacy controls, and network-free validation. It adds no new
device type, command, endpoint, platform, discovery field, or publishing path.

## 2. Build and repository state

- Candidate version: `0.1.0` in `manifest.json`.
- Baseline: local clean `main` commit `120dfe6`.
- Preparation branch: `codex/wp-0003-v0.1.0-release-candidate`.
- Publication state: no final release, tag, HACS submission, transfer, commit, or
  push is asserted by this report.
- Approved owner decisions: GoDeeGo Productions; intended namespace
  `GoDeeGo-Productions`; intended final repository URL
  `https://github.com/GoDeeGo-Productions/home-assistant-grit-hub`; MIT licence;
  and GitHub Private Vulnerability Reporting.
- Operational state: the destination, transfer, final-URL verification, and
  Private Vulnerability Reporting enablement remain pending.

Final release must select an immutable reviewed commit after all unchecked items
in [Release checklist](RELEASE_CHECKLIST.md) are resolved.

## 3. Test environment

Live outcomes below were supplied from acceptance testing against a real GRIT
installation and Home Assistant environment. No address, credential, hub/device
identifier, customer data, payload, topology, or other installation detail is
recorded. This release-preparation work itself uses fabricated identifiers,
fake REST/MQTT clients, bounded waits, and local static validation only.

## 4. Installation acceptance

**Live-validated:** a clean HACS Custom Repository installation completed. The
normal flow requested the API URL, raw token, and certificate preference,
discovered the hub ID, and requested only the broker address when the API did
not provide a usable LAN address. This repository remains outside the default
HACS catalogue.

## 5. API authentication acceptance

**Live-validated:** authentication succeeded through `GET /api/hub` using the
raw token as an exact bearer-header value. The current-hub response identified
the hub. Rejected authentication maps to `invalid_auth`; public health alone is
not accepted as proof of token access.

## 6. MQTT discovery and readiness acceptance

**Repository contract and prior live evidence:** internal defaults include port
1883, TLS off, verification on where applicable, keepalive 60, and provisional
read-only credentials. Readiness requires connection, successful subscribe, and
the exact matching successful SUBACK for `grit/<hub-id>/+/+/#`. Normal
`connect_async()` `None` behavior is accepted. MQTT never publishes.

**Automated evidence:** fake Paho tests cover lifecycle races, early and stale
callbacks, exact message-ID handling, reason codes, validation bounds, and
privacy. Final totals are recorded by the work-package validation report.

## 7. Gate acceptance

**Live-validated:** gates hydrate accurately from retained MQTT, update
immediately after GRIT-side changes, and Home Assistant gate commands update and
confirm without false failure. The implementation captures the MQTT boundary
before REST and requires a newer matching observation. No optimistic or
unproven REST gate state is used.

## 8. RFID acceptance

**Live-validated:** mixed real reader states hydrate accurately; Home Assistant
RFID commands update and confirm; GRIT-application changes update promptly; and
offline readers become unavailable. The strict individual REST `state` is
authoritative. MQTT `s`/`st` events only trigger bounded debounced refresh and
no personal RFID user data is retained.

## 9. GRITLock acceptance

**Live-validated:** the system GRITLock locks and unlocks. The bounded REST
command is `PUT /api/hub/lockout` with a boolean state. Display and confirmation
use settled current-generation trigger `/gl` MQTT consensus, with strict REST
trigger fields provisional at startup or after disconnect.

## 10. Collector acceptance

**Live-validated:** the collector turns on and off, and its delayed shutdown
transition completes without false confirmation. Individual collector detail is
the deterministic state and confirmation source; a newer online settled match is
required. No equivalent transition contract is claimed for other switch types.

## 11. Hub control acceptance

**Repository-derived:** implemented controls are Refresh All, per-device refresh
and locate, GRIT service restart, a disabled-by-default Hub reboot, and System
LED Brightness with post-write REST refresh confirmation. The system GRITLock is
covered separately. A final explicitly authorized live check of LED and any
other intended controls remains an unchecked release item.

## 12. Reconfigure and token rotation acceptance

**Live-validated:** replacement token reconfiguration succeeds, device and entity
identities are preserved, no duplicate devices/entities are created, unrelated
options remain preserved, and reload occurs once. Validation happens before
mutation; invalid API or MQTT inputs leave the entry unchanged.

## 13. Restart acceptance

**Live-validated:** Home Assistant restart retains correct integration behavior.
Setup and reconnect restore bounded MQTT readiness and request fresh telemetry;
failed setup and unload clean up clients, loops, tasks, waiters, and listeners.

## 14. Clean uninstall and reinstall acceptance

**Live-validated:** clean HACS installation completed. Normal uninstall and the
deterministic clean-removal procedure are documented. Final sign-off for both
normal uninstall and deterministic clean reinstall against the selected release
commit remains unchecked because the supplied outcome does not separately assert
both removal procedures.

## 15. Offline and failure-mode acceptance

**Automated evidence:** mocked tests exercise connection failure, authentication
failure, SUBACK failure and timeout, disconnect, cancellation, stale callbacks,
failed reads, contradictory confirmations, and unload. Bounds and coalescing
prevent uncontrolled refresh work. No live failure injection is claimed.

## 16. Privacy and redaction acceptance

**Repository-derived:** API and MQTT inputs are allowlisted before retention;
raw responses and payloads are not entity attributes; API error bodies are not
read; endpoint logs are bounded; MQTT logs omit topics, identifiers, payloads,
and credentials; production REST refuses redirects; and no diagnostics-download
module exists. A bounded log-redaction helper and manual-review checklist are
provided. Secret and history scans must be rerun on the final release commit.

## 17. Automated validation summary

The repository includes standard-library tests for API, authentication, config
flow, discovery, MQTT, coordinator reconciliation, entities, runtime setup,
manifest, documentation, and redaction. It also has HACS, Hassfest, and unit-test
GitHub Actions. Final local network-free validation ran 352 tests successfully;
one optional real-Paho smoke test was skipped because Paho was intentionally not
installed. All 31 Python files compiled in memory and parsed as AST, three JSON
files and seven YAML files parsed, the 512×512 brand image passed PNG structure
checks, and `git diff --check` passed. Official HACS and Hassfest results require
CI after an authorized push and were not executed locally.

## 18. Known limitations

- Experimental unofficial integration and provisional protocol knowledge.
- Direct MQTT mandatory, QoS 0, and no per-device staleness timer.
- One hub identity per config entry; limited multi-hub evidence.
- Dynamic device entity addition/removal requires reload.
- Provisional vendor-default MQTT credentials await author confirmation.
- No collector-style confirmation claim for solenoid, latch, or powerbank.
- Broad imported/generated endpoint catalogue retained for reference.
- Not in the HACS default catalogue and not yet a published final release.

## 19. Remaining release decisions

Resolved owner decisions are the **GoDeeGo Productions** display name, intended
`GoDeeGo-Productions` namespace and final repository URL, MIT licence and
copyright notice, and GitHub Private Vulnerability Reporting channel.

Operational implementation remains pending: create or verify the organization
and destination, transfer the repository, verify the final URL, enable Private
Vulnerability Reporting, confirm maintainers/CODEOWNERS and future commit
identity, set repository description/topics, update manifest links after
transfer, complete CI and final live acceptance, select the release commit, and
approve the tag, release notes, publication, and any HACS submission.

## 20. Final acceptance checklist

- [x] GoDeeGo Productions display name and intended namespace approved.
- [x] MIT licence and GoDeeGo Productions copyright notice approved.
- [x] GitHub Private Vulnerability Reporting approved as the security channel.
- [ ] Organization/destination created or verified and repository transferred.
- [ ] Final repository URL verified after transfer.
- [ ] GitHub Private Vulnerability Reporting enabled and verified.
- [ ] Remaining maintainer and commit-identity decisions approved.
- [ ] Full local validation is green on the final diff.
- [ ] HACS and Hassfest CI are green on the selected commit.
- [ ] Secret and complete-history reviews are accepted.
- [ ] Normal uninstall and deterministic clean reinstall are retested.
- [ ] Remaining implemented controls are live-tested only under explicit safe authorization.
- [ ] Final repository URLs and metadata are correct after transfer.
- [ ] Release commit, tag, notes, and distribution steps are approved.

**Acceptance status:** Conditionally accepted as v0.1.0 release candidate,
subject to completion of the release checklist and owner decisions.

See [Release checklist](RELEASE_CHECKLIST.md) and return to the
[README](../README.md).
