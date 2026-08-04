# Installation

GRIT Hub is an experimental Home Assistant custom integration. It is not yet in
the default HACS catalogue and `v0.1.0` is currently a release candidate.

## Before you begin

You need Home Assistant `2026.3.0` or newer, a reachable GRIT API base URL, a
raw bearer token accepted by `GET /api/hub`, and network reachability from Home
Assistant to the GRIT MQTT broker. Do not paste the `Bearer ` prefix with the
token. HACS installs this integration; it does not install a broker.

Keep an independent, safe means of physical access available during installation
and testing. Installing or configuring the integration must not be treated as a
safety or security validation.

## HACS Custom Repository

1. Open HACS and choose **Custom repositories**.
2. Paste this repository's final GitHub URL.
3. Choose **Integration** as the category.
4. Add the repository, then install **GRIT Hub**.
5. Restart Home Assistant.
6. Open **Settings > Devices & services > Add integration** and select
   **GRIT Hub**.

The repository has been transferred to GoDeeGo Productions and its verified
final URL is
`https://github.com/GoDeeGo-Productions/home-assistant-grit-hub`. Use that exact
URL and verify it in the browser before trusting an archive or installation.

## Manual installation

1. Download a trusted release-candidate archive.
2. Copy only the integration directory so the installed path is exactly
   `/config/custom_components/grit_hub`.
3. Restart Home Assistant.
4. Add **GRIT Hub** under **Settings > Devices & services**.

Do not copy tests, private references, logs, databases, caches, or repository
metadata into Home Assistant's configuration directory.

## Initial setup

The first page requests:

- **GRIT API URL** — for example `https://your-grit-server.example`.
- **Bearer Token** — the raw opaque token only, without `Bearer `.
- **Verify SSL** — leave enabled for a normally trusted HTTPS certificate.

The integration then:

1. Makes one bounded authenticated `GET /api/hub` request.
2. Retains the valid documented hub `id` for the MQTT topic.
3. Uses a valid `ipAddressEthernet` as the broker when supplied by the API.
4. If the address is missing or invalid, asks only for the GRIT Hub LAN hostname
   or IP address while retaining the hub ID.
5. Connects without publishing and subscribes at QoS 0 only to
   `grit/<hub-id>/+/+/#`.
6. Requires the exact matching successful SUBACK before allowing setup to
   complete.

The normal flow applies these internal defaults:

| Setting | Default |
| --- | --- |
| MQTT port | `1883` |
| MQTT TLS | Off |
| Verify MQTT certificate | On when TLS is used |
| MQTT keepalive | `60` seconds |
| REST interval | `30` seconds |
| MQTT credentials | Provisional vendor-default read-only values |

The provisional MQTT credential pair is centralized in source and pending
confirmation from GRIT's author. It is not displayed on the normal flow. Use
Advanced settings for an installation-specific least-privilege override.

Setup is bounded and fail closed. It does not publish, operate hardware, scan
hosts or ports, retry in the background, or guess another endpoint.

## Advanced settings

Choose Advanced when automatic validation fails or when the installation uses
non-default settings. Available overrides are:

- REST interval;
- MQTT broker host and port;
- MQTT topic hub ID;
- MQTT username and password;
- MQTT TLS and certificate verification;
- MQTT keepalive.

Leave both MQTT credential fields blank to use the provisional defaults. An
override password requires an override username. Prefer TLS with certificate
verification whenever broker traffic crosses an untrusted network.

## Verify the installation

After setup, verify without commanding equipment:

- the config entry reaches **Loaded**;
- the REST, Internet, and MQTT connectivity diagnostics are sensible;
- hub software and device-count diagnostics are populated where the API returns
  them;
- discovered devices appear under the expected GRIT Hub device;
- gate and GRITLock state become known only after their authoritative evidence;
- RFID readers with a valid individual detail response show their actual state.

Any live gate, lock, collector, locate, reboot, or device-command test requires a
separately stated and explicitly authorized manual procedure.

## Options and reconfiguration

The Options flow changes only the REST scan interval.

Use **Reconfigure** to change API and MQTT connection settings. Leave the API
token blank to preserve the stored token. Leave the MQTT password blank to
preserve it while a username remains configured; clearing the username also
clears the stored password. The replacement token and MQTT subscription are
validated before mutation. A successful reconfigure updates the existing entry
and reloads it once, preserving device and entity identity.

Rotate credentials at their source first, reconfigure the integration, and then
revoke the old credentials. Failed validation leaves the existing config entry
unchanged.

## Normal uninstall

1. Delete the GRIT Hub config entry from **Settings > Devices & services**.
2. Remove GRIT Hub through HACS, or delete the manual
   `/config/custom_components/grit_hub` directory.
3. Restart Home Assistant.
4. Revoke or rotate credentials at their issuing systems if they are no longer
   needed.

Do not edit `/config/.storage` manually.

## Deterministic clean removal

Use this sequence only for development, troubleshooting, or release acceptance:

1. Delete the GRIT Hub config entry.
2. Stop Home Assistant Core.
3. Remove `/config/custom_components/grit_hub` only if it is still present.
4. Verify both that component directory and its `__pycache__` are absent.
5. Start Home Assistant Core.
6. Remove GRIT Hub through HACS.
7. Verify `/config/custom_components/grit_hub` is absent.
8. Do not edit `/config/.storage`.

Use the Home Assistant UI, add-on controls, or host-management commands approved
for your installation. This repository deliberately does not provide commands
that assume a particular supervisor, container, host path, or shell.

See [Troubleshooting](TROUBLESHOOTING.md) for setup failures and safe log
redaction, or return to the [README](../README.md).
