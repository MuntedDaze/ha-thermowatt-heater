# Thermowatt next development release checkpoint

Owner task: attached master development request, 17 November 2026 (Hobart).
Source of truth: main `7553821dceb3bc78a67621399984bbc992567aea`, controller
0.15.1 / bridge 1.3.17. Work branch `codex/thermowatt-next-major`. The shared
checkout is isolated from Fable's separate registered worktree. Preserve
untracked `review-1b29be1/` and `uv.lock`; no live HA/vendor/MQTT access.

## Current checkpoint: implementation and independent review complete

Controller0.16.0 / bridge1.4.0 are in [PR42](https://github.com/MuntedDaze/ha-thermowatt-heater/pull/42).
Astra High independently accepted
`ff0307313882979c76ad825738dc9f000e909a07`; all32 final-head checks passed, including
all1622 tests on Python3.12/3.13/3.14. The complete local run also passed1622 tests.
No live operations or merge occurred.

- Real HA2026.10.4/2026.11.1, desktop1280/phone390 frontend, nativeamd64/aarch64,
  isolatedMQTT/lifecycle/demand and Supervisor checks passed on that code head.
  Final phone/desktop screenshots were inspected: current plan, readable labels
  and copyable report are confirmed.
- Owner's follow-up is presentation/documentation only: optional-boost help now
  explicitly describes both dedicated CT and separately configured experimental
  CT-free GoodWe operation, and explains that the switch alone cannot start boost.
  Updated source catalogue, generated English strings/settings guide, README and
  homeowner help; labelled the earlier CT-only checkpoint as historical.
- No controller, bridge, options, defaults, command protocol or safety logic changes.
  Versions remain0.16.0/1.4.0. Rebuild generators and run relevant regression/static
  checks; all final-head CI and fresh phone/desktop help inspection are required.
- The previous exact-head source archive matched all170 committed files. The
  wording increment requires a new final-head archive/checksum.
- Remaining work: wait for **all** final-head CI; inspect full-suite/static
  outcomes; verify the new archive's SHA/manifest/all files; check PR reviews;
  record the final SHA, checks and artifact in the PR handoff. Avoid another
  documentation commit merely to stamp passing CI; use the final PR record.
- Owner now explicitly authorises marking PR42 ready for review after all checks
  pass. Keep it unmerged until separate owner merge approval. No
  installation, authentication, automatic activation or heater operation is
  authorised. Fable's worktree and seven-view dashboard remain unchanged.

The entries below are chronological development history, not current results.

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

Historical progress (superseded by the current checkpoint above):

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

Independent review correction checkpoint:

- Astra High completed read-only review of0b374a2. TwoP1 and fiveP2 findings
  accepted; details/evidence in REVIEW.md. All seven have code corrections and
  targeted regressions (21 pass). Non-replay suite also passed. No new POST replay
  or auth-lock bypass found. Must obtain final independent corrected-diff review.
- Changes cover real-span irregular cadence, fully gated in-place peak adoption
  without commands, margin/lead cross-validation, quiet weekend-end baseline,
  fresh/actual quiet deadlines, original PV/grid event capture with rebinding,
  and diagnostic solar reasons/real timestamps. Original safety/temperature roles
  remain; no live operations. Source changes must now remain stable during tests.
- Fixed CI guide portability (OS time-zone alias lists), outdated HA menu assertion
  and old bridge DOCS baseline text. Actual HA same-turn PV dip/no-save pair tests added.
- Regeneration running in exec sessions6374 (five older replay artifacts) and
 96056 (new seasonal +20min-TTL artifacts). After they finish, rebuild comparison
  table with tools/build_polling_evidence.py; inspect outcomes and commit results.
- Full local run20366 was invalidated by source edits while it was still executing;
  do not claim it passed. Rerun the whole suite after current fixes/results settle.
- Review agent /root/independent_review is idle, available for authorised read-only
  follow-up final verification. Send corrected full diff/head and actual CI evidence.
- Initial corrected UI at0b374a2 passed both browser versions and was visually
  inspected (phone labels/translated states now readable, desktop2-column native
  sections). Latest final source still needs all checks and final screenshot verification.

Further correction after66aee0d follow-up:

- Astra accepted the original seven reproductions but identified two newP1 event
  races. Corrected raw CT callbacks to invalidate/reset only, retaining60s pairing
  and canonical executor-only positive CT votes. Added latched transient required
  meter loss through single-controller durable exit/START confirmation handling;
  impossible CT-free export cannot become a passing vote. No callback transport.
-25 focused review regressions pass;90 selected review/existing-interface tests
  pass. Actual HA same-loop grid outage/recovery added with commands blocked by
  missing MQTT/commissioning. Source is to be frozen for final regressions.
- Sessions6374/96056 completed replay regeneration from the previous correction;
  new event-capture fields are unused in those mocked-bus replays. Full final
  suite must reproduce all results from fresh imports; never claim mixed-source
  long-running test results. Old20366 remains invalidated, not passing evidence.
- Need commit corrected head, ask Astra for final readonly verification of the
  two remainingP1 reproductions and new races, run all final-head CI, inspect any
  failure, download/verify artifacts/screenshots and finish handoff without merge.

Final code checkpoint:

- Astra High independently accepted a197c5ce48fcf858bef616b529fdc0a0a8a0c450
  after verifying all nine findings; no further actionable defect. Read-only,
  no tests/live I/O by reviewer. Review acceptance remains conditional on final CI.
- Accepted head actual HA/core/combined monitoring, nativeamd64/aarch64,
  Supervisor and both desktop/mobile frontend workflows pass. Local full1622-test
  run is session43905 (.test-deps/next-major-verified-pytest.txt). No source edits
  are permitted during that run; subsequent work is documentation/artifact metadata.
- Final metadata increment fixes the CI source bundle to use the exact reviewed
  PR head, not GitHub's synthetic merge-test SHA. All final-head checks must pass.
- Remaining routine work: inspect full unit outcome/CI; correct real failures if
  any, obtain final artifact and verify manifest/all hashes/head, inspect final
  screenshots, update PR/handoff with exact head/results/checksum. Keep PR draft,
  unmerged and undeployed; owner approval still required for merge/live operation.

Final regression result/correction:

- Local complete suite:1621 passed, one comparison assertion failed. The new
  schedule caught a genuine5-minute app change at12:05 and entered owner hold;
  the assertion wrongly required it always to be missed. Corrected the test to
  compare disclosed detection with the recorded genuine owner-override event.
  No controller behaviour changed. Run the targeted seasonal comparison and all
  final-head CI; no further implementation changes are planned.
- Canonical CI source bundle for5efb2ee was verified: all170 source hashes and
  manifest match local exactly (ZIP creator metadata differs across OS only).
  The test-only commit needs a freshly verified exact-head bundle/checksum.

Final visual correction:

- Final screenshots exposed a read-only plan-summary sensor lagging one completed
  evaluation behind the requested-mode sensors. It now reads/subscribes directly
  to the existing executor's completed decision; no policy, command or polling
  logic changes. Actual HA asserts matching displayed/current plan immediately.
- Shortened one truncated electricity card heading. Regenerated only the separate
  homeowner dashboard; Fable's seven views remain untouched. Final-head CI and
  refreshed artifact/checksum/screenshot inspection remain the closing steps.
