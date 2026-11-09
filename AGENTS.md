# Thermowatt development and release workflow

These are the owner's standing instructions for
`MuntedDaze/ha-thermowatt-heater`, recorded on 2026-11-09. Later explicit owner
directions take precedence. Keep development modest and focused on reliable
status, modes, setpoints and verified existing controls; scheduling optimisation
belongs separately in Home Assistant/EMHASS.

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
