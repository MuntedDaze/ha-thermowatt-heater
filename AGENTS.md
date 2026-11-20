# Thermowatt development and release workflow

These are the owner's standing instructions for
`MuntedDaze/ha-thermowatt-heater`, updated on 2026-11-20. Later explicit owner
directions take precedence. Keep development focused on the final approved
45/62/70°C heating policy and trustworthy operation; EMHASS forecasts are
optional scheduling advice, not a prerequisite or an independent controller.

## Two-branch workflow (owner decision 2026-11-20)

- **`main`:** stable, owner-approved release source. Do not commit or push
  directly. Production installation is separately owner-controlled.
- **`dev`:** the single permanent working branch for Claude, Codex and
  Antigravity. New work begins here, based on the last approved `main`.
  Do not create routine `codex/*`, `claude/*`, `feature/*`, or audit branches.
- Work sequentially on shared files: one agent writes to `dev` at a time.
  Independent reviewers read the same exact commit, preferably in a detached
  read-only worktree. Never merge or write from that review worktree.
- Before editing, verify origin, HEAD, clean/dirty files, current worktrees,
  open PRs and that `dev` contains the intended latest work. Preserve owner
  changes and existing worktrees; never overwrite, reset, force-push or silently
  discard uncommitted work. If `dev` is checked out elsewhere, coordinate or
  safely reuse its existing worktree rather than creating another branch.
- When the whole release is tested and reviewed, create **one** PR from
  `dev` into `main` (not stacked PRs). Merge only after the final exact
  commit passes applicable CI and meets the owner-approval conditions below.
  Prefer squash merges and verify the resulting `main` tree matches the
  reviewed source. Then safely fast-forward/reset **only a clean `dev`** to
  `main` for the next cycle; never discard unmerged work.
- The old development branches and draft PRs are historical. Do not base
  fresh work on them or delete an unverified branch. Preserve unmerged work,
  branch references and worktrees until separately checked and approved
  for safe deletion. Closing an obsolete draft PR does not delete its code.

## Authoritative operating policy (2026-11-20)

[docs/OPERATING_POLICY.md](docs/OPERATING_POLICY.md) is the single source of
requirements. Read it before any behaviour change. A value found only in a
retired setting, default, parser structure, test, fixture, changelog or
`docs/history/` is never a current requirement. In particular the 0.7.0 morning
reserve (45 °C by 06:00, 42 °C by 07:00) is **cancelled**: Manual 45 °C overnight
with the heater's native hysteresis, no morning top-up and no morning alarm.

## Standing owner decision: variable-temperature hot water (2026-11-16)

Read [the owner's hot-water decision record](docs/decisions/HOT_WATER_TEMPERATURE.md)
before proposing heating-policy changes or writing an owner-facing status update.
The owner reports discussing the installation with a plumber, who advised that
the intended **short** 45°C target periods followed by heating above 60°C are
acceptable in this particular household. Treat that discussion as recorded owner
context, not a project-issued compliance certificate.

**Do not repeatedly re-open the generic 45°C storage/compliance debate** in
routine code reviews, PR descriptions, release notes, installation checklists,
daily status summaries or unrelated answers. The owner has explicitly asked for
that repetition to stop. Preserve the agreed **Manual 45°C overnight/weekend
baseline, Manual 62°C normal weekday storage, optional economical Manual 70°C
boost and existing peak-OFF policy**. Do not invent a new temperature gate,
rewrite the strategy or raise generic boilerplate as a blocker.

Keep detailed factual limitations in the technical safety documentation;
software cannot independently certify whole-tank temperatures or legal compliance.
Revisit the subject only if the owner requests a safety/compliance assessment,
new evidence indicates the intended reheating is not actually occurring, a
proposed change would extend low-temperature operation or impair native
protections, or another *material, specific* safety issue arises. State the
concrete new reason rather than repeating the old discussion. This instruction
does not authorise defeating native safety features or changing safety-critical
code without the existing review and owner-approval gates.

## Routine execution

1. Verify the working directory, GitHub origin, active worktree, branch and
   uncommitted changes. Use the existing `dev` branch for all routine development;
   preserve unrelated owner changes and do not create another development branch.
2. Implement only the requested scope, with applicable mocked regression tests.
3. Run all existing unit tests, static checks, native container tests and
   applicable CI workflows. Current checks include pytest, Ruff lint/format,
   compileall, Bash syntax, Python 3.12/3.13/3.14, native amd64/aarch64 image and
   isolated MQTT/lifecycle checks, and Supervisor schema validation. Inspect the
   current workflow definitions rather than assuming this list stays current.
4. When preparing a release, update the add-on version, both changelogs,
   relevant documentation and appropriate upgrade metadata. Validate preservation
   of credentials, tokens, guard state, options and MQTT entity IDs. Do not
   silently change configured cloud/command flags or authentication generation.
   Documentation-only changes do not require a release/version bump.
5. Create one PR from `dev` to `main`. For changes entirely within the
   automatic-merge scope below, wait for all required/applicable checks on the
   final commit to pass, check independent reviews and unresolved concerns,
   mark the PR ready and squash-merge into `main`. Do not stop merely to ask
   for routine approval in this scope.
6. Verify the PR actually merged, `main` has the exact reviewed source tree
   and expected add-on version, and synchronize `dev` from `main` only when
   doing so cannot overwrite unfinished work. Report tested/merged commits,
   checks, review results and remaining owner installation steps.

Never merge failed, pending, incomplete or unavailable required CI. Do not
bypass branch protection, use an administrator override, force a protected
update or merge while significant review concerns remain. If the execution
environment cannot complete a check or merge, report the exact outstanding
condition; do not claim completion.

## Automatic squash-merge scope

- Documentation and test changes.
- Read-only entity improvements.
- Logging and diagnostic improvements that do not alter authentication security
  behavior.
- Minor compatibility fixes without device-command or safety-behavior changes.

## Changes requiring explicit owner approval

- Authentication, tokens, lockouts or retry policies.
- Enabling or changing heater commands.
- Temperature safety limits or antibacterial protections.
- Automatic heating or fallback behavior.
- Credentials, permissions or significant dependencies.
- Any live Home Assistant deployment or physical heater operation.

Classify by the actual behavior of the full PR, not its title or changed file
names. A PR mixing routine changes with any approval-required change still
requires approval. Complete the authorised implementation and offline checks,
then leave it unmerged until the owner explicitly approves that merge.

GitHub merge approval never authorises Home Assistant deployment, live
authentication, cloud API requests or heater operation. Do not contact live
Thermowatt services, use real credentials, change authentication settings or
operate the heater without separate explicit authorisation. Tests use synthetic
credentials, mocked cloud HTTP and isolated services, never the owner's running
Home Assistant, Proxmox VMs or Docker infrastructure. Never log credentials,
tokens, API keys, sensitive response bodies or raw sensitive exceptions.

