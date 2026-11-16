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
- Implemented native copyable report/JSON download, allowlisted bounded event
  history, focused five-view dashboard, friendly sensor names and enum translations.
  Heartbeat publishes genuine completed timestamps at15min/semantic changes;
  exact internal evaluation remains unchanged. Diagnostic save failure is isolated.
- Initial actual HA2026.10.4/2026.11.1 desktop/mobile frontend passed at2fa7495.
  Screenshots were inspected; corrected a phone truncation and raw-state labels
  using native sections/enum translations. Final frontend rerun remains required.
- Owner handbook, full generated setting index, existing-system upgrade/rollback,
  local telemetry feasibility/unsent enquiry and actual-worker seasonal/short-TTL
  evidence are implemented. New exact-commit CI source artifact includes hashes.
- Last full regression:1590 passed/one artifact-fixture failure; that fixture and
  current guide/dashboard packaging requirements are corrected and targeted tests
  pass. Full final suite and newly added seasonal reproduction still required.
- Current request evidence: Smart≈234 vs717 CT-free summer,284 vs743 CT winter.
  CT-free target outcomes match fixed30; real-model CT cost differences up to
  about$0.13/week are visible. Missed heavy-draw/outage targets are not concealed.
  Synthetic20min sessions reduce savings; no vendor TTL claimed.
- Implementation is ready for the authorised independent read-only review once
  the current review checkpoint is committed. Remaining: resolve review/CI findings,
  final-head full checks/screenshots, verified exact-commit artifacts/handoff.
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
