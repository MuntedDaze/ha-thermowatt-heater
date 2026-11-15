# One controlled integration, then normal Update

No merge, live installation or repository-cache modification has occurred.
The owner has chosen merge-then-normal-update. **PR36 source-cache staging is
unsupported.** Its helper and load-only smoke are removed in this candidate.
Do not run an old owner ZIP's helper. A branch pin with no remote counterpart
breaks store refresh and can be replaced by Supervisor recovery. Do not patch
remote-tracking refs as a new installation route.

## Repository prerequisites and integration strategy

The public repository default is `main`, verified 15 November 2026 at
`04a8d3d819003d46ea0237f39613de0f0cda401a`. It is an ancestor of the preserved
PR36 head `649491381cd58cbb8ad65210453f67c551934fab`. Fable's reviewed
`4c078f0802faaafc5d5fcc4264af7894b28fc95c` is also an ancestor. The candidate
therefore includes the integrated seven-view dashboard without separately
merging PR32 or changing its worktree.

Prepare the new remediation draft **against main**. It is a single integration
of the already-reviewed stack plus the focused fixes. Independent reviewers can
inspect the small delta from 6494913 separately. This strategy avoids exposing
older unsafe/intermediate candidates as normal store updates.

Future merge order, only after separate explicit approval:

1. Review the final integrated tree and changed safety paths; all final-head CI
   and reviews must pass. Verify main has not changed. If it has, integrate its
   changes on development, rerun checks and review the resulting exact tree.
2. Approve **one integrated squash merge into main**. Do not independently merge
   #27/#32/#33/#34/#35/#36 first. The integrated candidate already contains them;
   their branches/checkpoints remain preserved. Closing superseded drafts is a
   separate housekeeping decision after the owner approves the integration.
3. Verify main's resulting commit and source tree, bridge 1.3.17/controller 0.13.0,
   unchanged `thermowatt_boiler` slug/domain/entity identities, and checks. Record
   that merge SHA alongside the reviewed development SHA. A squash changes the
   SHA; compare the actual tree, not an expected original commit ID.
4. Only then, with installation approval, follow the owner's **normal Update**
   procedure. No release/tag/public distribution is needed or authorised.

This is a prepared strategy, not an assertion that main contains the candidate.
The draft must remain unmerged until owner approval. Existing PRs stay untouched.

The installed source must already be this same repository's default-main
registration. **Preserve its exact registered URL**, including `.git` spelling,
and full installed ID. Supervisor derives the repository identity from its
registered source; adding a `#branch`, local source or another URL can create a
different identity. The actual owner's registered ID/version must be read and
recorded during approved installation; no live access was used to guess them.
If a different source/local installation exists, stop and prepare its specific
migration rather than uninstalling, copying `/data` or adding a second bridge.

## Preservation contract

| Object | Required result |
|---|---|
| Add-on | Same full repository-prefix + `thermowatt_boiler` ID, same private data |
| Options | Credentials/MQTT/topic, explicit cloud/command flags, poll/retry values and generation retained |
| Authentication | Tokens, blocked/retry/in-flight locks and cooldowns retained; no automatic generation change |
| Commands | Existing pending outcomes reconciled, never replayed; command-state version remains1 |
| Usage | Category accounting/cooldowns retained; no counter reset |
| Controller | Same domain/config entry/registry/source maps and master state; deliberately disable before upgrade |
| Learning | Existing files preserved; no automatic CT/hardware/learning qualification |
| New authority | Adaptive/long quiet/learning qualifications default false |
| Existing temperature roles | Preserve the agreed45/62/70 roles and guarded protocol; no new restrictive temperature gate |

Bridge-first, controller-second, dashboard-third remains the compatible order.
The new bridge understands the existing closed four-state payloads. No unrestricted
setpoints or legacy-policy bypass is introduced. Additive controller fields are
optional; older persisted state loads without manufacturing observations.

## Recovery and what is actually tested

Isolated CI uses real Supervisor2026.10.5/2026.11.0 `GitRepo.load`, **entire pull
body**, identity hashing and catalog loading against a disposable local origin.
An environment-local Git URL rewrite preserves the real public origin string
while ensuring no external connection. The test advances main from a synthetic
old version to the actual candidate, repeats unchanged refresh, then offers a
synthetic higher-version forward recovery. Private-state fingerprints remain
unchanged. This exercises the refresh path omitted by PR36's staging smoke.
It is a CI fixture, not an owner command or Supervisor daemon/install test.

Existing mocked upgrades test real bridge loading of historical authentication
states/options and MQTT IDs. Additional regressions cover pending/restart state,
controller Restore/Undo and low-baseline gate defaults. Real HA checks preserve
the registry and validate combined generated contracts.

After live authentication/commands, prefer a separately reviewed **forward
recovery build** with a higher offered version on the same main branch. It keeps
current private safety state. A code recovery is not permission to reduce guards
or repeat an uncertain command. Older bridge code may not support Manual 62;
qualify its actual supported prior before any downgrade.

Backup restore is a distinct path. Full HA and cold Proxmox backups must include
the actual installed app image/data, configuration and recovery key. Before any
live state changes, test the sealed restore in a disconnected VM, never a second
online account client. **A real HA backup/image restore has not been performed
or proven in this development environment.** Do not call the synthetic Git test
a successful VM restore. After live activity, rolling tokens/locks/pending/usage
back to a sealed snapshot needs review and preservation/reconciliation of newer
safety state. A raw source archive is never an authentication backup.

Sources: [official Supervisor Git update implementation](https://github.com/home-assistant/supervisor/blob/2026.11.0/supervisor/store/git.py),
[repository identities](https://github.com/home-assistant/supervisor/blob/2026.11.0/supervisor/store/repository.py),
[HAOS file access and maintenance](https://www.home-assistant.io/common-tasks/os/),
[HA backups and recovery](https://www.home-assistant.io/common-tasks/general/backups/).

Use [the owner guide](../pre-review/OWNER_INSTALLATION.md) for the normal steps.
