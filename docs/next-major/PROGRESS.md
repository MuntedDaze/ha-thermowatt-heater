# Thermowatt next development release checkpoint

Owner task: attached master development request, 17 November 2026 (Hobart).
Source of truth: main `7553821dceb3bc78a67621399984bbc992567aea`, controller
0.15.1 / bridge 1.3.17. Work branch `codex/thermowatt-next-major`. The shared
checkout is isolated from Fable's separate registered worktree. Preserve
untracked `review-1b29be1/` and `uv.lock`; no live HA/vendor/MQTT access.

Implementation order:

1. Heating/compatibility: new 12-hour override targets 62, preserve active legacy
   override expiry/target and unresolved intent; weekend measured-PV comfort
   latch and optional 70 boost; configurable confirmed-withdrawal cooldown.
2. One existing bridge-owned polling scheduler: bounded long overnight leases,
   pre-boundary observation, decision freshness, owner-detection disclosure,
   restart/fixed fallback and HTTP-category comparisons. Authentication guards
   remain; optimise only supported/session-expiry evidence, never guess lifetimes.
3. Homeowner UI: existing IDs, friendly names, focused responsive interface,
   experimental CT-free meter setup from genuine evidence, clear blocking
   reasons, copyable authenticated text/JSON diagnostics and bounded event log.
4. Useful fresh pre-peak low-water alerts replacing rigid morning deadlines;
   actionable deduplicated faults; reduce Recorder writes without changing
   local evaluation, command or watchdog timing. Review EMHASS quality/fallback.
5. Replay actual policy/controller/bridge across seasons/failures; review high-
   risk paths, full unit/static/native/HA/frontend CI, homeowner documentation,
   upgrade/rollback and verified source artifacts/checksums, GitHub PR/handoff.

Compatibility rules: keep domain/storage/entity IDs and MQTT command protocol;
add state/options rather than reset them. Do not change the owner's existing
settings, enabled state or credentials on upgrade. New permissions are explicit
choices, never silently inferred from a meter being present. No duplicate
vendor client, scheduler, heater arbiter or household-energy dashboard redesign.
Do not claim physical qualification or vendor/local-interface evidence from
synthetic tests. Existing exact-prior/confirmation/authentication/backoff and
durable protective exit remain mandatory.

Candidate versions will be controller 0.16.0 and bridge 1.4.0 if the extended
polling protocol requires it. Release artifacts are for owner installation;
development does not deploy, authenticate or operate the installed system.
Review/merge decisions must satisfy the standing AGENTS.md owner-approval rule
for behaviour/authentication changes and all final-head checks.

Progress (implementation incomplete):

- Override62, legacy active-target/expiry migration, weekend PV comfort latch/
  sunset bounds, confirmed cooldown10, new preferences and real-meter setup are
  implemented. Required weekday planner, exact-prior/confirmation and durable
  protective exit remain. Fresh pre-peak35C assessment replaces production
  morning45/42 alerts; missed62 target no longer generates an emergency warning.
- Smart v3 extends the existing 180-second lease scheduler with bounded8h quiet
  nights/12h experimental maximum, pre-boundary checks and fixed30 crash fallback.
  New explicit polling choices preserve all old flags when set to existing.
  Smart ordinary status GETs use the existing bounded401 refresh/retry; POST,
  command pre-read, confirmation and discovery preparation retain old safeguards.
- CT-free startup adds inverter/house consistency checks; continuing an already
  authorised session relies on the genuinely live signed grid, so asynchronous
  auxiliary reports cannot turn passing clouds into immediate protective OFF.
  No nominal element credit, no commissioned-CT downgrade.
-218 targeted new/legacy policy, controller, CT-free and adaptive tests pass.
  Ruff and bridge strict type check pass. New tests cover core timings and auth.
- Candidate versions: controller0.16.0 / bridge1.4.0. No artifact/release yet.
- Still required: diagnostics/report view/download, homeowner dashboard and
  sensor presentation/Recorder-noise work, complete actual-HA/browser/regression
  updates, scenario replays/category metrics, documentation, artifacts and review.
- Owner explicitly authorised a separate READ-ONLY final reviewer after the
  implementation is complete. Claude Fable5.2 is unavailable; use GPT-6 Astra
  at High effort (model override authorised by owner) with full master request,
  base architecture, whole diff and tests. Do not spawn that final review early.
  Resolve findings, rerun tests, then request final read-only verification.
- No merge approval has been inferred; apply standing AGENTS owner gate to the
  actual full PR. Complete all authorised offline implementation and evidence.

Python: `C:/Users/jacob/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`.
Local dependencies: absolute `.test-deps` in PYTHONPATH. Use UTF-8 stdout for
Python scripts. Git writes/network use the configured sandbox escalation.
