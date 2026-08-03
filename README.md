# GRIT Hub Home Assistant Integration

![Temporary neutral GRIT Hub icon](custom_components/grit_hub/brand/icon.png)

GRIT Hub is an unofficial, experimental Home Assistant custom integration for
GRIT Hub systems. It uses the GRIT REST API for discovery, reconciliation and
physical commands, and a dedicated direct MQTT connection for live device
state.

This project is not affiliated with, endorsed by, or supported by GRIT or GRIT
Automation. It is provided as-is, without support or warranty.

> [!CAUTION]
> GRIT systems can control gates and other physical access-control equipment.
> This integration must not be relied upon as the sole security or
> access-control mechanism. Maintain independent physical controls, safety
> devices and manual access procedures. Do not represent or use this software
> as a safety, security or life-safety system.

## Status and compatibility

- Version: `0.1.0`
- Integration domain: `grit_hub`
- Minimum supported Home Assistant version: `2026.3.0`
- Distribution: HACS Custom Repository or manual installation
- Status: unofficial, experimental and provided as-is

Home Assistant 2026.3 or newer is required because this repository uses local
custom-integration brand images, which Home Assistant supports from 2026.3.
Runtime validation is currently based on static checks and deterministic mocked
tests; repository tests do not contact a broker, GRIT API or physical device.

## Architecture and supported functionality

The integration has two required data paths:

- **REST API:** authenticates with a bearer token, discovers devices, polls for
  reconciliation, and sends explicitly bounded physical operations.
- **Direct MQTT:** uses its own Paho MQTT v3.1.1 client, subscribes at QoS 0 to
  `grit/+/+/+/#`, validates the configured hub ID, and applies an allowlist of
  sanitized live state and diagnostic fields.

The integration does not use or require Home Assistant's MQTT integration. HACS
installs this integration only; it does not install, configure or provide an
MQTT broker. Broker access must already exist. The GRIT API token and MQTT
credentials are separate and may differ.

The MQTT client only subscribes. It never publishes MQTT messages or commands.
All gate, cover, switch, locate and device-command operations use the REST API.
No MQTT payload, complete topic, broker address, credentials, hub ID or device
ID is retained in entity attributes or intentionally written to logs.

The manifest uses `local_polling` because the required REST reconciliation path
polls directly from the configured API. The integration is hybrid: live state
is pushed over MQTT, and either configured endpoint may be located elsewhere.
Home Assistant's IoT-class field does not express that topology separately.

## Prerequisites

For the normal installation path, obtain a reachable GRIT REST API base URL and
bearer token. The integration authenticates first and then attempts to discover
the MQTT broker and topic hub ID.

An existing MQTT broker must still be reachable from Home Assistant; HACS does
not install or provide one. Normal setup uses the documented Ethernet address
and hub ID returned by the API, plus the v0.1.0 connection defaults described
below. If validation fails, the installer opens the Advanced form.

The repository contains one narrowly authorized provisional vendor-default,
read-only MQTT credential pair, centralized in `const.py`. It is applied only
when no Advanced credential override is stored, is never displayed or copied
into a normal config-flow result, and is pending confirmation from GRIT's
author. This exception does not permit any installation-specific credential or
any other embedded secret. Use a dedicated least-privilege override when the
deployment supports one. The API bearer token is never reused for MQTT.

## Installation through HACS

This repository is not in the default HACS catalogue. Once the GitHub
repository is public, add it as a custom repository:

1. Open HACS in Home Assistant.
2. Open the HACS menu and select **Custom repositories**.
3. Enter `https://github.com/dionweisler-ux/home-assistant-grit-hub`.
4. Select **Integration** as the category and add the repository.
5. Install **GRIT Hub** and restart Home Assistant.
6. Go to **Settings > Devices & services > Add integration**, search for
   **GRIT Hub**, and complete the configuration flow.

## Manual installation

1. Download this repository.
2. Copy `custom_components/grit_hub` to
   `/config/custom_components/grit_hub` in the Home Assistant configuration
   directory.
3. Restart Home Assistant.
4. Go to **Settings > Devices & services > Add integration**, search for
   **GRIT Hub**, and complete the configuration flow.

## Initial configuration

The first page asks only for:

- **GRIT API base URL:** for example `https://your-grit-server.example`. No
  installation-specific default is included.
- **GRIT API bearer token:** enter the token value without the `Bearer` prefix.
- **Verify GRIT API SSL certificate:** keep enabled for a normally trusted HTTPS
  certificate.

After successful REST authentication, setup performs a deterministic discovery
sequence:

1. It authenticates against the configured REST API, then reads the current hub
   through the existing documented request `GET /api/hub/1` with a short
   timeout.
2. It accepts only a valid documented 32-character hexadecimal `id` as the MQTT
   topic hub ID and a valid `ipAddressEthernet` value as the broker address.
3. It makes one bounded connection attempt to that exact address on port 1883,
   with TLS disabled, keepalive 60 and the provisional read-only defaults. It
   does not fall back to the public API hostname or inspect other endpoints.
4. It subscribes at QoS 0 only to
   `grit/<documented-hub-id>/+/+/#`. Successful connection and subscription are
   sufficient; discovery does not wait for a message. If a message arrives
   during the bounded attempt, its hub segment must exactly match the REST hub
   ID.
5. It shows the discovered broker and hub ID for confirmation. The credential
   defaults are not shown or stored in the flow result.

If discovery cannot confirm every required value, **Advanced MQTT settings**
asks only then for:

- REST scan interval;
- MQTT broker host and port;
- MQTT topic hub ID;
- optional MQTT username and password;
- MQTT TLS and certificate-verification settings;
- MQTT keepalive.

Discovery never publishes, sends a command, scans addresses or ports, retries
in the background, or changes the GRIT installation. It stops after the bounded
attempt and fails closed to manual entry.

After the config entry is created, normal setup still performs an initial REST
refresh and requires the configured MQTT client to connect and subscribe within
its bounded readiness timeout. If MQTT is unavailable, Home Assistant keeps the
entry not ready and retries normal setup later instead of loading partially.

## Reconfiguration and credential rotation

Open **Settings > Devices & services**, select **GRIT Hub**, and use the
integration's **Reconfigure** action to update API, MQTT or TLS settings. On the
reconfiguration form:

- leave the API token blank to retain the stored token;
- leave the MQTT password blank to retain it while the username remains set;
- clear the MQTT username to clear its stored password as well.

Reloading the config entry after a change stops the old MQTT client before the
replacement starts. Rotate API and broker credentials at their sources first,
then reconfigure the entry. Keep a safe independent access method available
while testing credential changes.

The regular options flow changes only the REST scan interval.

## TLS guidance

Enable TLS whenever MQTT crosses an untrusted network. Certificate verification
is enabled by default for both HTTPS and MQTT TLS. Disabling verification can
expose credentials and device state to interception and should be limited to a
controlled diagnostic situation with a separately verified endpoint. Prefer a
valid certificate or an appropriately trusted private certificate authority.

## Entities and services

The integration creates a single GRIT Hub device with:

- the system-wide **GRITLock** lock entity;
- REST/integration, internet and MQTT connectivity binary sensors;
- IP address, software version, software branch, status and device-count
  diagnostics;
- the optional physical-buttons-disabled diagnostic;
- a 0-100 system LED brightness control that refreshes and confirms observed
  state after writing;
- a GRIT service restart button;
- a Hub reboot button that is disabled by default.

Discovered equipment retains the existing per-device diagnostics, switches,
covers, refresh buttons and locate buttons. MQTT remains subscribe-only; all
commands use explicit REST methods. A GRITLock or LED request is not reported as
confirmed merely because its HTTP request completed.

The bounded `grit_hub.device_command`, `grit_hub.refresh_device` and
`grit_hub.locate_device` services also remain. Services, buttons, locks, covers
and switches may cause physical activity. Review the target and site conditions
before invoking them. There is no arbitrary HTTP endpoint service, shutdown
button, raw MQTT control, backup/restore control, SSH control or tunnel control.

## State, availability and reconciliation

REST polling remains the authoritative discovery and reconciliation mechanism.
Validated MQTT messages can update known devices immediately, and the
coordinator preserves only bounded MQTT state across an unambiguous same-device
REST refresh.

Covers and switches are available only when the last REST update succeeded, the
MQTT subscription is connected, and the device has not explicitly reported
itself offline. If the broker connection is lost, live covers and switches
become unavailable but retain their last known state. Reconnection and a
successful subscription restore broker availability. The always-available MQTT
connection diagnostic shows the broker state.

The integration does not currently implement per-device MQTT staleness timers.
A device that stops publishing without reporting offline may therefore retain
its previous availability. MQTT does not infer cover movement; only validated
position/open values are shown. Devices added after setup may require an
integration reload before new entities appear.

## Known limitations

- The API schema and supported GRIT firmware remain experimental. Discovery is
  based on GRIT API version 1.1.1008 and uses only documented current-hub fields.
- Automatic discovery requires a valid `id` and `ipAddressEthernet` from
  `/api/hub/1`, plus a successful broker connection and exact subscription. It
  performs no hostname fallback, network scan, port scan or background retry.
- The bundled read-only MQTT credential defaults are provisional pending
  confirmation from GRIT's author. Installations that differ must use the
  Advanced credential overrides.
- Normal setup uses MQTT port 1883 without TLS. Deployments requiring a
  different port or TLS must use Advanced settings.
- One config entry represents one configured API and MQTT hub identity;
  multi-hub behaviour has not been redesigned or broadly validated.
- Direct MQTT is mandatory for setup and live controllable-entity availability;
  REST-only deployments are not supported by the current runtime.
- MQTT uses QoS 0, so delivery is not guaranteed.
- Dynamic entity addition and removal is not implemented.
- There is no per-device MQTT staleness timeout or cover movement inference.
- The imported/generated endpoint catalogue in `const.py` remains broad and may
  contain duplicated or unused routes.
- The repository is not part of Home Assistant Core or the default HACS
  catalogue.

## Troubleshooting

- **Integration does not appear:** confirm the directory is exactly
  `/config/custom_components/grit_hub`, restart Home Assistant and refresh the
  browser.
- **Automatic discovery opens Advanced:** confirm `/api/hub/1` returns a valid
  hub ID and Ethernet IP, and that the broker is reachable from Home Assistant
  at that address. Enter the required overrides; discovery deliberately does
  not scan the local network or try another host or port.
- **Entry remains not ready:** verify both the REST API and MQTT broker are
  reachable from Home Assistant. MQTT must connect and subscribe during setup.
- **REST connection fails:** check the API base URL, token, network path and
  certificate-verification setting.
- **MQTT connection fails:** check broker host, port, credentials, listener
  protocol, firewall rules, hub ID and TLS settings. HACS does not provide the
  broker.
- **TLS fails:** confirm the hostname matches the certificate and that Home
  Assistant trusts its issuing certificate authority. Avoid disabling
  verification as a permanent fix.
- **Entities are missing:** verify the devices are returned by the GRIT API,
  then reload the integration after discovery.
- **Live entities become unavailable:** check the MQTT Connection diagnostic.
  The last state is intentionally retained during broker loss.
- **Commands do not work:** stop repeated attempts if equipment may move. Check
  the physical site independently before further testing.

When sharing logs, issue reports or screenshots, remove credentials, broker and
API addresses, hub/device identifiers, customer information and payload data.
Do not attach Home Assistant diagnostics or backups without reviewing them.

## Privacy, secrets and backups

Home Assistant stores the API token, endpoint settings and any Advanced MQTT
credential override in the config entry, so protected backups may contain them.
The narrowly authorized provisional read-only MQTT defaults live only in
`const.py`; normal setup does not copy them into the config entry, entities,
diagnostics or coordinator data. Protect backups accordingly and rotate
installation credentials after suspected exposure. Never commit `.storage`,
logs, databases, diagnostics, cookies, tokens or site configuration to this
repository.

## Removal

Remove the GRIT Hub config entry from **Settings > Devices & services**, remove
the integration through HACS (or delete the manual
`custom_components/grit_hub` copy), and restart Home Assistant. Removing the
integration does not revoke API or MQTT credentials; revoke or rotate them at
the GRIT API and broker if they are no longer needed.

## Contributing

Focused pull requests and reproducible bug reports are welcome. Preserve
existing behaviour unless a change is explicitly justified, keep changes small,
and use deterministic mocked tests for API, MQTT and command paths. Automated
tests must never contact a live system or actuate equipment. Never include
credentials, private installation details, customer data, diagnostic payloads
or live-equipment test results that could identify a site.

## Licence

This project is licensed under the [MIT License](LICENSE).

The included icon is a temporary neutral project asset. It contains no vendor
logo or text and may be replaced later with an original project identity.
