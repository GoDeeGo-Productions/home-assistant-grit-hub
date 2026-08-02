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

Before installation, obtain and verify:

- a reachable GRIT REST API base URL and bearer token;
- an existing MQTT broker hostname and port reachable from Home Assistant;
- the GRIT MQTT hub ID used in topics;
- MQTT credentials if the broker requires authentication;
- the broker's TLS and certificate-verification requirements.

Use dedicated, least-privilege credentials where the GRIT deployment supports
them. Do not reuse the API token as the MQTT password unless the installation
specifically requires it.

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

The configuration flow asks for:

- **GRIT API base URL:** for example `https://your-grit-server.example`. No
  installation-specific default is included.
- **GRIT API bearer token:** enter the token value without the `Bearer` prefix.
- **Verify GRIT API SSL certificate:** keep enabled for a normally trusted HTTPS
  certificate.
- **REST scan interval:** polling interval from 10 to 3600 seconds.
- **MQTT broker hostname:** for example `mqtt.example.invalid`.
- **MQTT broker port:** the listener port exposed by the existing broker.
- **MQTT topic hub ID:** the hub component expected in GRIT MQTT topics.
- **MQTT username and password:** optional broker credentials; a password
  requires a username.
- **Use MQTT TLS:** enables transport encryption.
- **Verify MQTT TLS certificate:** validates the broker certificate when TLS is
  enabled.
- **MQTT keepalive:** from 1 to 65535 seconds.

Setup performs an initial REST refresh and then requires the MQTT client to
connect and subscribe successfully within a bounded readiness timeout. If MQTT
is unavailable or the subscription fails, Home Assistant keeps the config entry
not ready and retries later instead of loading partially.

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

The integration creates entities from devices returned during initial REST
discovery:

- binary sensors for REST connectivity, MQTT connection and known per-device
  MQTT online state;
- diagnostic sensors for hub status, device count and device status;
- per-device MQTT RSSI, firmware and last-received diagnostics when those
  allowlisted values have been received;
- switches for supported controllable device types;
- covers for supported gates;
- refresh and locate buttons.

It also retains the bounded `grit_hub.device_command`,
`grit_hub.refresh_device` and `grit_hub.locate_device` services. These services,
buttons, covers and switches may cause physical activity. Review the target and
site conditions before invoking them. There is no arbitrary HTTP endpoint
service.

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

- The API schemas, endpoint coverage and supported GRIT firmware remain
  experimental.
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

Home Assistant stores the API token, optional MQTT username/password and endpoint
settings in the config entry. They are not source-code defaults, but they may be
included in protected Home Assistant backups. Protect backups accordingly and
rotate credentials after suspected exposure. Never commit `.storage`, logs,
databases, diagnostics, cookies, tokens or site configuration to this
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
