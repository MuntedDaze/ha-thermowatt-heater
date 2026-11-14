# Smart controller implementation checkpoint

Branch: `codex/smart-controller-next`.
Baseline: `1b29be165ddc61eb0b2e64a69eea9a435f7f7a53` (PR #27, unchanged).
Owner request: implement the Thermann brief, backend first; Fable owns dashboards.

## Boundaries

Development and synthetic offline tests only. No merge, deployment, live cloud,
MQTT, credentials or heater operation. Bridge 1.3.13 and controller 0.9.1 release
candidate are preserved; this branch is development work, not an install package.
Keep untracked `review-1b29be1/` and `uv.lock` untouched.

## Plan and status

1. Implemented: sustained optional weekend import returns to Manual 45 even
   with a sunny forecast; full-cover ten-minute qualification avoids buying
   discretionary partial-grid heat. Passing clouds retain five-minute debounce;
   ordinary weekend spacing remains (up to 15 minutes of exposure after a start).
   Only peak withdrawal/meter-loss OFF bypass spacing; confirmation/auth guards
   remain. Future status cannot authorize a command or poison the watermark.
2. Implemented: generic W/kW CT with entity/unit commissioning stamp; optional
   Wh/kWh input; invalid/negative/ambiguous/stale/future/pre-boot handling;
   source-time deduplication and ≤60 s grid pairing; exact H−G conservation.
   Inferred state is diagnostic only. Optional heat requires CT; essential
   off-peak heat does not. Acquisition, balance and policy are separate.
3. Implemented: Recorder event interface; covered measured power integration;
   optional counter epochs/recovery; compact ≤40 clean heating sessions;
   draw/gap/command-change exclusion and bounded save cadence; conditional ETA
   ranges with idle/unknown suppression. Calibration requires ≥10 independent
   sessions on ≥3 days and remains diagnostic pending held-out/hardware evidence.
4. Implemented: one advisory scheduler, explicit flag default off; bounded
   heating/stable caps, consequential reasons, command-status reuse, deduplication
   and guard-aware blockage. Actual fixed bridge polling/auth/budgets unchanged.
5. Implemented: independent equal-service cost/request replays, feed-in-value
   veto for optional peak heat, conservative measured-plateau planning, an
   optional-exit request reserve, verified-tariff gate and future-status
   confirmation correction. Existing withdrawal/45/70 defaults retained; the
   existing economic margins are now visible preferences with validation.
6. Fable handoff incorporated at `4c078f0802faaafc5d5fcc4264af7894b28fc95c`:
   raw CT/energy mappings only, signed raw diagnostics, explicit steady-zero
   freshness regression and persistent meter-loss notification. Stable completion,
   fixed/shadow poll, learned-rate/confidence and request-budget sensors added.
   Fable owns dashboard/monitoring files; none changed or merged here.

## Resume

Check `git status --short`, branch and `git log -5 --oneline` before editing.
Read this checkpoint, the source and relevant tests; do not repeat the audit.
Audit sources inspected: ENGINEERING-AUDIT, DECISIONS-AND-PLAN,
POLLING-AND-THERMAL and results in `review-1b29be1/`.
Python 3.12 is available at
`C:/Users/jacob/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`.
Set `PYTHONPATH` to the absolute `.test-deps` directory for pytest/Ruff/mypy.
Workflow definitions: tests.yml, shadow-controller.yml, deployment-readiness.yml.
Native Docker/HA and Supervisor checks must run in isolated CI if Docker is absent.

## Evidence

Initial local HEAD and GitHub PR #27 head match the audited SHA. PR #27 remains
open/draft. No tracked owner edits were present. Tests and subsequent commit
anchors will be recorded here at each increment.

Increment 1: five new regressions ran against baseline: three reproduced bugs,
two existing guard behaviours passed. Full suite: **998 passed** (Python 3.12).
Ruff lint/format on project source, both workflow strict mypy targets,
compileall and Bash syntax passed. The untracked audit replay scripts do not
pass project Ruff rules; excluded from local checks, not modified or committed.
Docker is absent: native amd64/aarch64, HA and Supervisor matrices await CI.
Initial full baseline run: 992 passed, one overnight-baseline simulation failed;
the same test passed in isolation and the full post-change suite passed.
Increment 1 commit: find by subject `Fix optional import withdrawal and protective peak OFF`.
Commit: `4d404a2`.

Increment 2 full suite: **1024 passed**, Python 3.12. Focused final checks after
making the pure snapshot fail-closed by default: 102 passed. Ruff lint/format,
both strict mypy targets and compileall pass. Bash unchanged from increment 1.
The direct-meter cloudy replay now measures 0.90 kWh peak import, matching
Astra's direct trace; it is not the old inferred 0.75 kWh result. Hardware
checks remain unverified in CT_COMMISSIONING.md. No install package/version bump.
Increment 2 commit subject: `Use verified generic circuit power for optional heat`.
Commit: `b9620a8`.

Increment 3: **1032 passed**, Python 3.12; Ruff lint/format, both strict mypy
targets, compileall passed. Tests cover deduplication, outages, restart, counter
reset/jump/remap, disturbed cycles, independent learning, uncertainty and event
serialization/source-time labels. See TELEMETRY_INTERFACE.md for Fable's backend
contract. Ordinary history writes are ≤15-minute cadence plus session completion
and unload; an abrupt crash may lose unsaved integrated intervals. Native meter
counter/HA Recorder remain primary. No raw DB or dashboard changes.
Increment 3 commit subject: `Collect measured heating history and controller telemetry`.
Commit: `ac6643d`.

Increment 4: **1041 passed**, Python 3.12; Ruff lint/format, both strict mypy
targets and compileall pass. Comparison-enabled and disabled mocked bridge runs
produce identical HTTP and command counts. Injected timing tests cover caps,
duplicate callbacks, command-read reuse, imminent decisions, future status and
guard blockage. Real missed-event/detection-delay claims need independent event
truth; shadow telemetry explicitly labels that limitation. See POLLING_SHADOW.md.
Increment 4 commit subject: `Compare bounded adaptive polling without changing cloud traffic`.
Commit: `d6e800d`.

Draft backend PR: https://github.com/MuntedDaze/ha-thermowatt-heater/pull/33,
stacked against `codex/audit-fixes-0.9.1` so PR #27 stays intact. No ready/merge
transition is authorised. Fable's PR #32 stays independent and unmerged.

CI on `d6e800d`: Python 3.12/3.13/3.14, both native image/MQTT/lifecycle/demand
jobs and both Supervisor schemas passed. Both actual-HA jobs failed the explicit
upgrade-added-entity allowlist because the new sensors were not listed. The
allowlist is now extended by exact suffixes; old-identity preservation assertions
remain. Final-head CI must verify this correction before claiming readiness.

Increment 5/handoff evidence: focused tests reproduced future confirmation,
uneconomic peak start, nominal-only duration and missing exit reserve, then
passed with corrections. New cases cover steady 0 W expiry/republication,
signed reversed CT diagnostics, rejecting known dashboard wrappers, raw-meter
notification/resolution, tariff gating, economic settings, conditional poll
timestamps and reproducible simulations. Full suite: **1059 passed**, Python
3.12. Ruff lint/format, both strict mypy targets, compileall and diff whitespace
checks passed. Native Bash syntax already passed; CI repeats it on every head.
The independent replay yields 108/60/51 modelled HTTP calls for fixed30/fixed60/
adaptive, with detection/phase limits explicitly labelled. No annual savings.
Final-head CI is the remaining software gate. Commit subject:
`Guard economic dispatch and complete raw-meter telemetry handoff`.

## Current release gates and exact next steps

1. Resume in the original worktree on `codex/smart-controller-next`; inspect
   `git status --short` and `git log -6 --oneline`. Do not touch Fable's worktree,
   the audit directory, `uv.lock`, PR #27, main or the release candidate.
2. Run/inspect final-head PR #33 checks: all Python/static, native amd64/aarch64,
   HA 2026.10.4/2026.11.1 and Supervisor 2026.10.5/2026.11.0 jobs must pass.
   If a job fails, fix the cause and validate that new final head. No merge.
3. Review `TELEMETRY_INTERFACE.md` against Fable's reviewed contract; only after
   backend review/readiness consider a separately authorised integration of
   PR #32. No dashboard files are present in this backend branch.
4. Hardware gates remain: electrician-selected exclusive raw HWS channel,
   sign/phase/units, independent energy check, steady-zero reporting ≤120 s,
   real outage/recovery and native 45/70 cycle observations. Nothing installed.
5. Learning/adaptive gates: independent clean sessions, held-out prediction
   coverage and decision/cost validation; vendor session inactivity unverified.
   Learned slopes remain diagnostic; actual polling is fixed. Do not switch to
   real adaptive polling or use learned rates to relax any guard.
6. A future release needs owner-approved version/upgrade metadata and offline
   packaging. Bridge 1.3.13 and candidate controller 0.9.1 remain unchanged in
   identity/version. No installation, auth, MQTT or physical heater operation is
   authorised by this development work.

Isolation independently verified: Fable's registered worktree is
`C:/Users/jacob/Documents/ChatGPT/ha-thermowatt-heater-fable`, branch
`fable/thermann-energy-dashboard`; this branch uses the original path exclusively.
