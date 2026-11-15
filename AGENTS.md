# Thermowatt development and release workflow

These are the owner's standing instructions for
`MuntedDaze/ha-thermowatt-heater`, recorded on 2026-11-09. Later explicit owner
directions take precedence. Keep development modest and focused on reliable
status, modes, setpoints and verified existing controls; scheduling optimisation
belongs separately in Home Assistant/EMHASS.

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

1. Verify the working directory, intended GitHub origin, branch and uncommitted
   changes. Work on a dedicated development branch, normally prefixed `codex/`.
   Preserve unrelated owner changes.
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
5. Create a PR. For changes entirely within the automatic-merge scope below,
   wait for all required/applicable checks on the final commit to pass, check
   reviews and unresolved concerns, mark the PR ready and squash-merge into main.
   Do not stop just to request routine PR approval in this scope.
6. Verify the PR actually merged and main contains the expected changes and
   add-on version. Report the work, tested commit, squash commit, version,
   validation results and any remaining owner installation steps.

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

## Existing exception: PR #3, version 1.3.4

PR #3 changes token-refresh and lockout behavior. Retain its owner-review gate:
report final-head checks and merge readiness, but do not mark it ready or merge
it under the routine automatic-merge permission. It must remain unmerged until
the owner specifically approves its merge. Deployment needs separate approval.
