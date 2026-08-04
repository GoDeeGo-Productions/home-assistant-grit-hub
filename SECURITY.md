# Security policy

GRIT Hub controls access-control equipment. Treat vulnerabilities, credentials,
installation topology, and operational data as sensitive.

## Supported versions

For the initial release, only the latest published `0.1.x` version will receive
security fixes. Pre-release candidates are supported on a best-effort basis for
release preparation only. Older development snapshots and unmodified source
exports are unsupported. This project provides no service-level agreement,
response-time guarantee, or warranty.

## Reporting a vulnerability

Submit vulnerabilities privately through **GitHub Private Vulnerability
Reporting** using this repository's **Security > Report a vulnerability**
function. This is the approved reporting channel for GoDeeGo Productions.

Private Vulnerability Reporting must be enabled and verified on this repository
before `v0.1.0` is published. If **Report a vulnerability** is not
available, do not disclose the vulnerability publicly. A minimal public issue
may state only that the private reporting function is unavailable; it must not
include vulnerability details, installation data, endpoints, or reproduction
steps.

Never disclose any of the following in an issue, pull request, discussion,
screenshot, attachment, diagnostic, or log excerpt:

- GRIT API tokens or authorization headers;
- MQTT usernames or passwords;
- hub IDs, device IDs, complete MQTT topics, or subscription codes;
- private IP addresses, hostnames, network topology, or Wi-Fi details;
- email addresses, email credentials, cookies, or personal/customer data;
- raw API responses, raw MQTT payloads, diagnostic payloads, databases, backups,
  `.storage`, or unredacted installation logs.

Use only fabricated values when a public reproduction is needed. The bug-report
form and [Troubleshooting guide](docs/TROUBLESHOOTING.md) explain minimum safe
redaction, but automated redaction cannot prove a file is safe.

## After suspected exposure

1. Stop sharing or uploading the affected material.
2. Revoke or rotate the GRIT API token at its issuing system.
3. Rotate any installation-specific MQTT credentials at the broker.
4. Reconfigure the existing Home Assistant entry with the replacements.
5. Revoke old sessions, cookies, or other credentials exposed in the same data.
6. Review backups, shell history, logs, issue attachments, forks, caches, and
   CI artifacts for copies.
7. Do not assume deleting a public post removes it from mirrors or history.

Keep a separate safe access method while rotating credentials. Never test a
security report by operating physical equipment without a separately stated and
explicitly authorized manual procedure.

See [Contributing](CONTRIBUTING.md) for secure development rules and the
[release checklist](docs/RELEASE_CHECKLIST.md) for the outstanding enablement
check.
