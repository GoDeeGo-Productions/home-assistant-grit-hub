# Repository transfer guide

The approved public owner is **GoDeeGo Productions**, using the intended GitHub
namespace `GoDeeGo-Productions`. The intended final repository URL is:

`https://github.com/GoDeeGo-Productions/home-assistant-grit-hub`

These are approved owner decisions, not evidence that the organization,
destination repository, transfer, or final URL is operational. This guide does
not authorize or perform those actions.

## 1. Prerequisites

The organization display name, intended namespace and URL, MIT licence, and
GitHub Private Vulnerability Reporting channel are approved. Before transfer,
confirm maintainers, future commit-identity policy, transfer window, rollback
owner, current clean release commit, and backups through ordinary Git remotes.

## 2. Create and configure GoDeeGo Productions

An authorized owner creates or verifies the **GoDeeGo Productions** organization
at the `GoDeeGo-Productions` namespace, enables appropriate account security,
and confirms its public profile. Verify spelling and ownership before creating
or accepting the destination repository.

## 3. Transfer the repository

Use GitHub's repository transfer workflow only after both owners approve the
exact source and destination. Transfer to `GoDeeGo-Productions` with repository
name `home-assistant-grit-hub`, then verify the intended final URL. Do not mark
the URL confirmed or make the repository public as an incidental step.

## 4. Permissions and security reporting

Grant least-privilege maintainer roles, require multi-factor authentication where
appropriate, and remove obsolete collaborators or deploy keys. Confirm who can
administer settings, releases, Actions, and security reports. Enable and verify
GitHub Private Vulnerability Reporting so the repository's
**Security > Report a vulnerability** function is available before `v0.1.0` is
published.

## 5. Branch protection

Create or verify rules for the default branch: pull-request review, required
HACS/Hassfest/unit checks, dismissal behavior, force-push protection, and branch
deletion policy. Avoid rules that make emergency security maintenance
impossible without a documented owner process.

## 6. Secrets and Actions

Inventory Actions permissions, repository/environment secrets, variables,
webhooks, apps, deploy keys, and tokens. This integration should need no runtime
secret in CI. Rotate anything whose ownership or audience changed and keep
workflow permissions read-only unless a job demonstrably requires more.

## 7. HACS implications

A custom-repository installation uses the repository URL selected by the user.
After transfer, verify GitHub redirects and HACS behavior using the intended
final URL. A future default-catalogue submission is a separate owner decision
and must reference the final public location.

## 8. Git redirects

GitHub commonly redirects old repository URLs after transfer, but redirects are
not a permanent release contract. Test browser, archive, issue, clone, and Git
remote behavior without relying on the old owner in public documentation.

## 9. Update local remotes

Each maintainer verifies the current remote before changing it, then uses the
approved destination after transfer:

```text
git remote -v
git remote set-url origin https://github.com/GoDeeGo-Productions/home-assistant-grit-hub.git
git remote -v
```

Do not run these commands until transfer succeeds and the destination URL is
verified.

## 10. Update README, manifest, and HACS references

Prefer relative documentation links. Only after transfer, replace the current
owner's absolute `documentation` and `issue_tracker` values in `manifest.json`
with the operational final repository and issue URLs. Recheck README installation
wording, `hacs.json`, badges, workflows, package metadata, examples, and release
scripts. This release-candidate update intentionally leaves manifest URLs and
codeowners pointed at the current repository.

## 11. Update CODEOWNERS

Add or change CODEOWNERS only after valid GoDeeGo Productions teams or
maintainer accounts exist. This repository intentionally does not create a
speculative CODEOWNERS file before transfer. Confirm paths and ownership against
branch protection, then update `manifest.json` codeowners at the same review
boundary.

## 12. Verify issue, security, and release links

Check manifest links, issue forms, pull-request template, SECURITY instructions,
Private Vulnerability Reporting, release notes, assets, compare links, source
archives, Actions, and external references. Confirm old links redirect safely
and new links are canonical.

## 13. Perform a final clean installation

Using the verified final organization URL and selected immutable commit/release,
perform an explicitly authorized clean HACS Custom Repository install, initial
setup, restart, normal uninstall, and deterministic clean reinstall. Record only
redacted outcomes in the acceptance report.

## 14. Preserve authorship facts

Transfer changes visible repository ownership. It does not erase or rewrite
historical commit authorship, committer identity, issue authorship, or existing
public forks. Communicate this accurately.

## 15. Do not rewrite history by default

Do not rewrite Git history, author metadata, tags, or release objects unless the
owner explicitly approves a separately reviewed migration with a justified
privacy or legal requirement. A transfer is not itself a reason to rewrite
history.

## Reference inventory before transfer

Approved future-owner references now appear in `LICENSE` and release
preparation documentation. Current-repository references intentionally remain in:

- `custom_components/grit_hub/manifest.json` documentation, issue tracker, and
  codeowner;
- `AGENTS.md` initial repository target.

After transfer, update those current-owner references and re-audit README,
manifest, `hacs.json`, CODEOWNERS, workflows, badges, docs, templates, tests,
comments, and examples.

See [Repository metadata](REPOSITORY_METADATA.md),
[Release checklist](RELEASE_CHECKLIST.md), and the [README](../README.md).
