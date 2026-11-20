# Repository branch retirement audit — 20 November 2026

This is a **preservation-first** inventory, not an instruction to delete branches.

## Release and active workflow

- PR #50 was approved after 32/32 checks and an independent PASS on reviewed head
  `07bd8bab0748f977dcc34cea1cd42b3d4f9e3f57`.
- Merged as `c93279198360689bc2599fb4e8b0bfcb9e62611b` on `main`.
  GitHub git-tree SHA for both the reviewed head and merged commit is
  `240dfdd7182e739ce9cf28671894991a29e57109`.
- Permanent branches: `main` (release) and `dev` (development).
  See [AGENTS.md](../AGENTS.md).
- Historical draft PRs **#27–#36** were closed with archival explanations.
  They were **not merged during cleanup**; source branches and Git history remain.

## Remote branch inventory

The GitHub branches API showed **54** branches after creating `dev`:
`main`, `dev`, and **52** historical branches.

All 52 were compared with the new `main`. Results:

| Classification | Branch count | What this actually proves |
|---|---:|---|
| Fully behind `main` by ancestry | 1 | No unique commits are reachable only from that branch |
| Diverged from `main` | 51 | History differs, **not** proof of missing functionality; squash merges create divergent histories |
| Of the diverged branches, source tree confirmed identical to `main` | At least 1 | `codex/final-release` has the same Git tree as the released commit |

The one fully-behind branch is
`codex/bridge-1.3.10-off-cmd8-fresh-status`. It is a **candidate** for deletion
only after verifying that no agent worktree, automation, open task or owner
workflow depends on its name.

`codex/final-release` is source-tree-identical to `main`, but was associated
with Claude's active release worktree. **Do not delete until worktree usage
has been checked.**

The remaining **50 divergent historical branches** are **not approved for
deletion** by this ancestry-only audit. Some may contain work superseded by
squash merges; some may preserve experiments, old dashboards or unique files.
Review their concrete differences against the released tree and preserve any
useful work before removing references.

Particularly sensitive existing worktrees/branches:
`codex/thermowatt-next-major` (the older Claude primary workspace),
`codex/final-release` (the former Claude release worktree), and
`fable/thermann-energy-dashboard` (an earlier read-only dashboard project).
Do not alter an agent's untracked local files or remove a checked-out branch.

## Required checks before any future branch deletion

1. Refresh `origin`; verify `main` and `dev` and inspect all
   `git worktree list --porcelain` and `git status --porcelain` results.
2. Verify the branch does not back an open PR, deployed source,
   active worktree, unpublished feature or unfinished task.
3. Compare the complete source tree, meaningful changed files and
   commits against the current `main` and `dev`. Squash-merged commit
   ancestry alone is **not** sufficient evidence for deletion.
4. If unique content exists, retain it or explicitly archive/reconcile it
   after review. Preserve recoverability of deleted refs if required.
5. Delete only individually verified obsolete refs, without force-updating
   `main`/`dev`. Record exactly which were removed and what was retained.

## Historical external beta mirror

The pre-existing `.github/workflows/mirror-to-beta.yml` had a push trigger
that automatically attempted a **force-push of `dev` to
`waterheater-dev/ha-thermowatt-heater-beta:main`**. The beta repo's most recent
recorded push was 1 February 2026. On the first new `dev` push, the job
failed because `BETA_REPO_TOKEN` was unavailable; **no beta push occurred**.

As part of this approved two-branch cleanup, automatic mirroring was
**disabled**, preserving the workflow only for explicit manual dispatch from
`dev` with the confirmation input `MIRROR-DEV-TO-BETA`. Its original
credential requirement and external target are unchanged; the historical
beta repository was not altered. Do not run that manual action without
separate owner instruction.

## Outstanding admin setup

At the time of the audit, GitHub reported `main.protected = false` and no
repository rulesets. Configure protection to block direct pushes/force pushes,
require the `dev` → `main` PR review/check workflow, and retain the separate
owner authorisation for safety-critical releases. This has **not** been
configured by the audit.

No Home Assistant installation, commands, tokens or heater automation were
changed during this repository housekeeping.
