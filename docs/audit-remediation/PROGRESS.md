# PR36 audit remediation checkpoint

## Current PR37 parked-OFF follow-up

Owner requests one notification correction from independently re-reviewed
`94a7dd4cee49901d972ece2606315ac97ca3e314`. Keep the same isolated branch/PR37 and
all prior recovery heads; no merge/install/live operation. Preserve45/62/70 and
all command/auth/polling behaviour; F8 is closed and not reopened.

The gap is real: fault lock clears controller.heater; the actual executor then
returns HOLD before peak/holiday checks. A blanket unknown-state warning would
be false during legitimate OFF. Implemented a diagnostic-only current-policy
restoration target from the last genuine OFF, consumed only by alert supervision.
The actual HOLD/command remain unchanged. Fresh uncontrolled reports invalidate
older OFF evidence; unavailable entities preserve it. No schema/authority change.

19 new actual-executor/bridge regressions pass. The earlier 94-case focused run
passed before the last pending-POST restart test was added. Lint/format, both strict mypy targets, compileall,
generated energy checks and Bash syntax pass. Full suite 1440 passed before the
last added test; all three week-report regressions remain unchanged. A final
full-suite rerun with all 1441 tests will run on the committed fix;
Final local rerun including the added pending-POST restart case, plus final-head
actual HA/native/Supervisor CI and reviews, are required after push.
If replay reports change, verify only corrected diagnostic notifications differ;
never conceal command/HTTP/energy/cost changes. Keep candidate versions unchanged.

Next: finish full suite, commit/push the narrow fix and this handoff, inspect all
final-head CI, then update PR37 with exact final SHA/results and the short review
link. Do not make a post-CI source commit just to attest to its own SHA.
[Focused review handoff](PARKED_OFF_REVIEW.md). Historical checkpoints follow.

## Earlier remediation checkpoint

Owner request read in full from the 15 November attachment. Source findings and
all accompanying evidence read from `.audit-2026-11-15/REVIEW_REPORT.md`,
`test_adv_review.py`, `adv_output.txt` and `week_replay_summary.txt`. Preserve
those independent files, PR36 at 6494913 and all older draft heads.

Worktree: `C:/Users/jacob/Documents/ChatGPT/ha-thermowatt-heater`, new isolated
branch `codex/audit-remediation-normal-install`. Fable remains separately at
`.../ha-thermowatt-heater-fable`, branch `fable/thermann-energy-dashboard`, 4c078f0.
Owner untracked audit and uv.lock are untouched. No live access/merge/install/
authentication/MQTT/heater operation or enablement is authorised or performed.

Draft PR #37: https://github.com/MuntedDaze/ha-thermowatt-heater/pull/37
First pushed remediation commit f6596e89859ee914f376a17bca19c7246c2af9bf.

Implemented, final validation in progress:

- F1: source-cache installer removed; real Supervisor load/pull/catalog smoke
  replaced with normal main update and forward-recovery test, isolated local
  origin and private-state fingerprint checks. Normal owner guide rewritten; no source-cache installer remains.
- F2: persisted last-observed OFF/restore timer and distinct 30-minute warning,
  including restart and fault tests. Owner phone-notification, independent evaluation watchdog and outage runbook
  commissioning requirements documented. No retry/backoff change.
- F4: due refresh finishes before persisting pending; failures refuse without
  implying a heater POST. Actual POST timeout still remains uncertain. Slow
  refresh rechecks exact-prior freshness/queue age. Targeted tests pass.
- F5: empty discovery retries at fixed intervals, reports no_devices; adaptive
  sync is inside the tick exception boundary. Targeted tests pass.
- F6: CT-free running required heat never pauses using contaminated raw export;
  raw export remains useful for choosing starts. Low-threshold test passes.
- F8 owner correction: household45/62/70 is a fixed requirement following plumber
  discussion. Removed the proposed low-baseline gate and hygiene monitor entirely.
  Document official requirements/native-protection limitations without claiming
  independently established compliance. Fresh generic installation62 fallback
  remains as before; existing household roles/default45 are unchanged.
- DST transition tests cover both changes and fixed-AEST event deadline timing.

Current validation: targeted bridge/controller/upgrade regressions pass; all three
week replay outputs are byte-equivalent JSON to PR36. Ruff lint/format, both strict
mypy targets, compileall, generated energy files and Bash syntax pass. Full local
suite is running after the final corrections. The first run exposed only stale
version/report expectations; metadata is updated and reports reproduced.

First full corrected local suite passed; the final suite including completed-
evaluation heartbeat coverage is running. Initial actual HA/combined package,
optional-watchdog schema and native checks pass. The real Supervisor load/pull/
forward-recovery body completed, exposing a fixture assertion that used Git's
rewritten get-url instead of the stored configured URL. It is corrected to read
remote.origin.url, retaining both canonical URL spellings and all real pull calls.

Next: push the final CI-fixture/doc/checkpoint increment. Inspect all final-head
CI and reviews, finish exact suite/static/link checks, build optional source
handoff, and record final SHA/workflows/bundle evidence in PR #37 rather than a
post-CI commit. Never merge/install/contact vendor or HA; independent safety,
physical commissioning, inactivity and frontend/backup-restore evidence remain.

Prepared integration strategy: one new draft PR targeting main, containing
the complete already-reviewed stack and Fable ancestry, with focused audit delta
identified against 6494913. This avoids publishing unsafe intermediate versions.
GitHub main/default branch were verified at04a8d3d on15 November; main and Fable
4c078f0 are ancestors. Recheck main,
all preserved heads and final mergeability before reporting readiness; merge
requires separate owner approval. No public release/licence work.

Python: C:/Users/jacob/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe;
PYTHONPATH absolute .test-deps. Git mutations require approved tool escalation.
Never print embedded app key or private audit payloads. No subagents requested.
