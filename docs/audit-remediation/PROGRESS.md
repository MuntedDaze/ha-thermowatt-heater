# PR36 audit remediation checkpoint

Owner request read in full from the 15 November attachment. Source findings and
all accompanying evidence read from `.audit-2026-11-15/REVIEW_REPORT.md`,
`test_adv_review.py`, `adv_output.txt` and `week_replay_summary.txt`. Preserve
those independent files, PR36 at 6494913 and all older draft heads.

Worktree: `C:/Users/jacob/Documents/ChatGPT/ha-thermowatt-heater`, new isolated
branch `codex/audit-remediation-normal-install`. Fable remains separately at
`.../ha-thermowatt-heater-fable`, branch `fable/thermann-energy-dashboard`, 4c078f0.
Owner untracked audit and uv.lock are untouched. No live access/merge/install/
authentication/MQTT/heater operation or enablement is authorised or performed.

Implemented, validation in progress:

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

Next: commit/push implementation and documentation increment; new main-targeted
draft; inspect actual HA/native/Supervisor CI, fix any integration failure, final
full suite/static checks and final-head CI/reviews. Record exact final SHA and
workflow evidence in draft PR/completion report rather than a post-CI commit.

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
