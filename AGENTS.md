# GRIT Hub Home Assistant Integration

## Purpose

This repository contains an unofficial Home Assistant custom integration for
GRIT Hub systems. It is intended for installation through HACS as a custom
repository.

## Repository boundaries

- Work only within this repository.
- Never access or modify the Project Sentinel repository.
- Do not combine GRIT commits, branches or pull requests with Sentinel.
- Treat GitHub as the authoritative source for this project.
- Treat this repository as eventually public from the first commit onward.

## Development approach

- Preserve the behaviour of the currently working GRIT integration unless a
  change is explicitly required.
- Prefer minimal, reviewable changes over architectural redesign.
- Use focused `codex/*` branches for development.
- Do not commit credentials, passwords, tokens, cookies, API keys, private keys,
  customer information, private IP addresses or diagnostic payloads.
- Keep installation-specific settings out of source code.
- Use Home Assistant config entries for credentials and configuration where
  supported.
- Keep commits small and focused.
- Do not push or merge unless explicitly instructed.

## Physical safety

- GRIT controls physical gates and access-control equipment.
- Automated tests must never actuate physical equipment.
- Any live gate operation requires a separately stated and explicitly authorised
  manual test.
- Do not represent the integration as a safety, security or life-safety system.

## Initial release target

- Repository: `dionweisler-ux/home-assistant-grit-hub`
- Integration domain: `grit_hub`
- Distribution: HACS custom repository
- Initial version: `0.1.0`
- Status: unofficial, experimental and provided as-is
