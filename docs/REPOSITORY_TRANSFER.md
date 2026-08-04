# Repository transfer guide

The repository is expected to move from its current personal owner to a neutral
GitHub organization before public release. This guide prepares that change but
does not authorize or perform it.

## 1. Prerequisites

Approve the organization name, legal/licence position, maintainers, security
contact, future commit-identity policy, final repository name, transfer window,
and rollback owner. Confirm the working tree and selected release commit are
clean and backed up through ordinary Git remotes.

## 2. Create and configure the organization

An authorized owner creates the neutral organization, enables appropriate
account security, and confirms its public profile and contact settings. Do not
guess or reserve a name from this repository.

## 3. Transfer the repository

Use GitHub's repository transfer workflow only after both owners approve the
exact source and destination. Verify the repository name, destination account,
and transfer confirmation before accepting. Do not make the repository public
as an incidental step.

## 4. Permissions

Grant least-privilege maintainer roles, require multi-factor authentication where
appropriate, and remove obsolete collaborators or deploy keys. Confirm who can
administer settings, releases, Actions, and security reports.

## 5. Branch protection

Recreate or verify rules for the default branch: pull-request review, required
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
After transfer, verify GitHub redirects and HACS behavior, but document and test
the final organization URL. A future default-catalogue submission is a separate
owner decision and must reference the final public location.

## 8. Git redirects

GitHub commonly redirects old repository URLs after transfer, but redirects are
not a permanent release contract. Test browser, archive, issue, clone, and Git
remote behavior without relying on the old owner in public documentation.

## 9. Update local remotes

Each maintainer verifies the current remote before changing it, then uses the
approved final values:

```text
git remote -v
git remote set-url origin https://github.com/<organisation>/<repository>.git
git remote -v
```

Do not run these commands until the transfer is complete and the final URL is
approved.

## 10. Update README, manifest, and HACS references

Prefer relative documentation links. Replace owner-specific absolute
`documentation` and `issue_tracker` values in `manifest.json` with the final
repository and issue URLs. Recheck README installation wording, `hacs.json`,
badges, workflows, package metadata, examples, and release scripts. Do not use a
fictional interim owner.

## 11. Update CODEOWNERS

Add or change CODEOWNERS only after valid organization teams or maintainer
accounts exist. This repository intentionally does not create a speculative
CODEOWNERS file before transfer. Confirm the paths and ownership against branch
protection.

## 12. Verify issue and release links

Check manifest links, issue forms, pull-request template, SECURITY instructions,
release notes, assets, compare links, source archives, Actions, and any external
references. Confirm old links redirect safely and new links are canonical.

## 13. Perform a final clean installation

Using the final organization URL and selected immutable commit/release, perform
an explicitly authorized clean HACS Custom Repository install, initial setup,
restart, normal uninstall, and deterministic clean reinstall. Record only
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

## Current owner-reference inventory

At release-candidate preparation, owner-specific references remain where a valid
current URL/account is required:

- `custom_components/grit_hub/manifest.json` documentation, issue tracker, and
  codeowner;
- `LICENSE` copyright notice;
- `AGENTS.md` initial repository target.

README and new public docs avoid owner-specific prose and use relative links or
a final-URL placeholder. Re-audit the entire repository immediately after
transfer.

See [Repository metadata](REPOSITORY_METADATA.md),
[Release checklist](RELEASE_CHECKLIST.md), and the [README](../README.md).
