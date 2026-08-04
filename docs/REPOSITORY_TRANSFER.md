# Repository transfer guide

The repository owner is **GoDeeGo Productions**, using the GitHub namespace
`GoDeeGo-Productions`. The verified final repository URL is:

`https://github.com/GoDeeGo-Productions/home-assistant-grit-hub`

The organization/destination exists, the transfer is complete, and the final URL
and local `origin` have been verified. This guide records those completed facts
and the remaining post-transfer work; it does not claim a public release.

## 1. Prerequisites

The organization display name, namespace and URL, MIT licence, and GitHub
Private Vulnerability Reporting channel are approved. Maintainer ownership,
future commit-identity policy, Private Vulnerability Reporting enablement, and
selection of an immutable release commit remain open.

## 2. GoDeeGo Productions destination

The **GoDeeGo Productions** organization and destination repository have been
created at the `GoDeeGo-Productions` namespace. Account-security settings and
the public profile remain owner-administered GitHub settings and are not claimed
complete by this repository.

## 3. Completed transfer

The repository was transferred to `GoDeeGo-Productions` with repository name
`home-assistant-grit-hub`, and the final URL was verified. This does not claim
that `v0.1.0` has been tagged, released, published, or accepted by HACS at the
final URL.

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
HACS behavior using the final URL still requires release acceptance. A future
default-catalogue submission is a separate owner decision and must reference the
final public location.

## 8. Git redirects

GitHub commonly redirects old repository URLs after transfer, but redirects are
not a permanent release contract. Test browser, archive, issue, clone, and Git
remote behavior without relying on the old owner in public documentation.

## 9. Update local remotes

The local `origin` has been verified at the final destination. Maintainers can
use these commands to verify or correct another clone:

```text
git remote -v
git remote set-url origin https://github.com/GoDeeGo-Productions/home-assistant-grit-hub.git
git remote -v
```

No remote change is required in this clone.

## 10. Update README, manifest, and HACS references

Prefer relative documentation links. The manifest `documentation` and
`issue_tracker` values now use the verified final repository and issue URLs.
Recheck HACS acceptance, badges, workflows, package metadata, examples, and
release scripts before publication.

## 11. Update CODEOWNERS

The manifest retains the individual maintainer handle `@dionweisler-ux`, which
uses Hassfest-compatible codeowner syntax. It does not substitute the
organization account as a speculative codeowner. A repository CODEOWNERS file
and the final maintainer policy remain unverified release-checklist items.

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

## Reference inventory after transfer

Canonical repository references in `AGENTS.md`, the README, release
documentation, and manifest now use GoDeeGo Productions and the verified final
URL. The only retained former-owner handle is the manifest's individual
maintainer codeowner, as described above. HACS final-URL acceptance, Private
Vulnerability Reporting enablement, CODEOWNERS policy, badges, and publication
remain pending.

See [Repository metadata](REPOSITORY_METADATA.md),
[Release checklist](RELEASE_CHECKLIST.md), and the [README](../README.md).
