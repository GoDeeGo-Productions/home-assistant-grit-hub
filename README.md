# GRIT Hub for Home Assistant

![Temporary neutral GRIT Hub icon](custom_components/grit_hub/brand/icon.png)

GRIT Hub for Home Assistant is an unofficial Home Assistant custom component for
GRIT Hub gates, RFID readers, GRITLock, collectors, and hub controls. It combines
the authenticated GRIT REST API with subscribe-only MQTT state updates and is
designed for installation through HACS as a custom integration.

> **Release status:** a `v0.1.2` corrective patch candidate is in development.
> The `v0.1.1` release was published, passed live verification on Jeff's installation, but regressed Dion's installation and is superseded by the corrective `v0.1.2` release process.
> [`v0.1.0`](https://github.com/GoDeeGo-Productions/home-assistant-grit-hub/releases/tag/v0.1.0)
> remains the latest published release. This project is not a HACS
> default-catalogue listing.

This project is experimental, provided as-is, and is not affiliated with,
endorsed by, or supported by GRIT or GRIT Automation.

> [!CAUTION]
> GRIT equipment can operate gates and physical access-control devices. This
> integration must not be relied upon as the sole security or access-control
> mechanism. Maintain independent safety devices, physical controls, and manual
> access procedures. It is not a safety, security, or life-safety system.

## Features

- Gate covers with retained startup hydration, immediate MQTT updates, and
  post-command MQTT confirmation.
- One RFID lock entity per reader, using authoritative individual REST state and
  event-driven MQTT invalidation refresh.
- One system-wide GRITLock entity using bounded trigger MQTT consensus with
  provisional REST startup state. The corrective dual-mode fallback uses the
  fresh `gte=1` subset when present, or all fresh observations for an all-zero
  generation; `gls` remains authoritative.
- Collector, solenoid, latch, and powerbank switches, with deterministic
  individual-detail confirmation for collectors.
- Hub connectivity, software, device-count, MQTT, and per-device diagnostics.
- System LED brightness, service restart, hub reboot, refresh, and locate
  controls.
- Config-entry reconfiguration for API token rotation and MQTT settings.

## How it works

The integration has two required data paths:

- **REST API:** authenticated discovery, bounded reconciliation, and explicit
  device commands.
- **Direct MQTT:** config-flow validation subscribes to the exact hub-scoped
  topic. The dedicated runtime Paho MQTT v3.1.1 client subscribes at QoS 0 to
  `grit/+/+/+/#`, then the coordinator accepts only the configured hub ID. It
  never publishes.

Home Assistant's MQTT integration is not required. HACS installs only this
custom integration; it does not provide or configure a broker. See
[Architecture](docs/ARCHITECTURE.md) for the source-of-truth and confirmation
rules.

## Entity summary

| Platform | Main entities |
| --- | --- |
| `cover` | One gate cover per discovered gate |
| `lock` | System GRITLock and one lock per RFID reader |
| `switch` | Collector, solenoid, latch, and powerbank controls |
| `number` | System LED brightness |
| `button` | Refresh, locate, GRIT service restart, and disabled-by-default hub reboot |
| `binary_sensor` | REST, internet, MQTT, physical-button, and device connectivity |
| `sensor` | Hub information, device count, device status, RSSI, firmware, and last-received diagnostics |

The complete entity and authority reference is in [Entities](docs/ENTITIES.md).
Some buttons, switches, covers, locks, and services can cause physical activity.
Review the target and site conditions before using them.

## Requirements

- Home Assistant `2026.3.0` or newer.
- A reachable GRIT API base URL.
- A raw bearer token accepted by authenticated `GET /api/hub`.
- A broker reachable from Home Assistant, with access to the discovered GRIT
  hub topic.

The minimum Home Assistant version matches `hacs.json` and the local custom
integration brand-image support used by this repository.

## Install with HACS

This repository is not in the default HACS catalogue. To install it as a HACS
Custom Repository:

1. In HACS, open **Custom repositories**.
2. Paste the verified final repository URL:
   `https://github.com/GoDeeGo-Productions/home-assistant-grit-hub`.
3. Select **Integration** as the category.
4. Add the repository and install **GRIT Hub**.
5. Restart Home Assistant.
6. Go to **Settings > Devices & services > Add integration** and choose
   **GRIT Hub**.

The repository transfer to GoDeeGo Productions and the final URL are verified.
[`v0.1.0`](https://github.com/GoDeeGo-Productions/home-assistant-grit-hub/releases/tag/v0.1.0)
was published on 2026-08-04 after final live HACS Custom Repository acceptance
against the transferred repository URL. See the full [Installation
guide](docs/INSTALLATION.md).

## Manual installation

1. Download a trusted copy of this repository.
2. Copy `custom_components/grit_hub` to
   `/config/custom_components/grit_hub`.
3. Restart Home Assistant.
4. Add **GRIT Hub** from **Settings > Devices & services**.

## Configuration overview

The normal first page asks only for:

- GRIT API base URL, such as `https://your-grit-server.example`;
- the raw bearer token, without a `Bearer ` prefix;
- whether to verify the API TLS certificate.

Setup authenticates with `GET /api/hub`, retains its documented 32-character
hub ID, and uses a valid returned Ethernet address as the MQTT broker. If no
usable address is returned, setup asks only for the missing LAN hostname or IP
address. It retains internal defaults: port `1883`, TLS off, certificate
verification on where applicable, keepalive `60`, default REST interval `30`,
and the provisional vendor-default read-only MQTT credentials.

MQTT readiness requires connection, a successful subscribe call, and the exact
matching successful SUBACK for `grit/<hub-id>/+/+/#`. Setup never publishes,
scans the network, or creates the entry before validation succeeds. Advanced
settings provide broker, topic hub ID, credentials, TLS, keepalive, and polling
overrides. The API token and MQTT password remain secret fields.

## Documentation

- [Installation and removal](docs/INSTALLATION.md)
- [Entity reference](docs/ENTITIES.md)
- [Architecture and state authority](docs/ARCHITECTURE.md)
- [Troubleshooting and safe log redaction](docs/TROUBLESHOOTING.md)
- [Superseded v0.1.1 acceptance report](docs/ACCEPTANCE_REPORT_v0.1.1.md)
- [Superseded v0.1.1 patch-release checklist](docs/RELEASE_CHECKLIST_v0.1.1.md)
- [Historical v0.1.0 acceptance report](docs/ACCEPTANCE_REPORT_v0.1.0.md)
- [Historical v0.1.0 release checklist](docs/RELEASE_CHECKLIST.md)
- [Changelog](CHANGELOG.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)

## Known limitations

- This is an experimental custom integration, not Home Assistant Core and not a
  default HACS catalogue entry.
- Direct MQTT readiness is mandatory; REST-only operation is not supported.
- The provisional read-only MQTT defaults are pending confirmation from GRIT's
  author. Installations that differ must use Advanced overrides.
- MQTT is QoS 0 and has no per-device staleness timer.
- One config entry represents one API and MQTT hub identity; multi-hub behavior
  has not been broadly validated.
- Dynamic device entity addition and removal requires an integration reload.
- Gate state has no unproven REST fallback. RFID state comes from individual
  REST detail, not collection state or MQTT payload values.
- Collector-grade transition confirmation does not apply to solenoid, latch, or
  powerbank switches.
- The imported/generated endpoint catalogue remains broad and contains routes
  not used by the integration.

## Privacy and security

Config entries and protected backups may contain API and MQTT secrets. Never
share `.storage`, backups, databases, raw API or MQTT payloads, unredacted logs,
private addresses, hub/device identifiers, or customer and personal data.
Runtime data and entity attributes use bounded allowlists; raw REST and MQTT
objects are not exposed as entity attributes. The integration has no Home
Assistant diagnostics-download implementation.

Read [Security](SECURITY.md) before reporting a security issue. The approved
channel is GitHub Private Vulnerability Reporting through **Security > Report a
vulnerability**. It must be enabled and verified before publication; never place
vulnerability details or installation data in a public issue.

## Support and contributing

For a reproducible bug, use the repository bug-report form and include versions,
installation method, affected entity, expected and actual behavior, restart
behavior, and only redacted log lines. General protocol changes require evidence
for both states and both transitions, plus deterministic network-free tests.
See [Contributing](CONTRIBUTING.md).

## Licence

Licensed under the approved [MIT License](LICENSE). The included icon is a temporary,
neutral project asset with no vendor logo or text.
