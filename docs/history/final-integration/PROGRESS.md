# Final integration checkpoint

Branch `codex/thermann-final-integration`, original isolated worktree
`C:/Users/jacob/Documents/ChatGPT/ha-thermowatt-heater`.
Base PR #34: `d3e26f8d54003586f9d75c29ee781231581af9cb` (1155 tests, 18 CI jobs).
Confirmed remote PR heads on 2026-11-15: #27 `1b29be1`, #33 `cf97d5e`,
#34 `d3e26f8`, #32 `4c078f0`. All remain drafts and unchanged. Fable's separate
worktree is untouched. Owner untracked `review-1b29be1/` and `uv.lock` preserved.

## Approved scope and boundaries

Implement combined read-only monitoring/dashboard, real disabled-by-default
guarded adaptive polling, validated learning architecture, week-long integrated
simulations and practical future-ready configuration/commissioning documentation. No main/protected-branch
merge, installation, real Thermann/MQTT/authentication, heater operation,
credential/history rewrite, licence selection or release publication.
Draft PR #35 targets `codex/economic-dual-storage` (PR #34).

## Stages

1. A: inspected actual heads, AGENTS, recovery checkpoints and interfaces.
   Bridge owns HTTP/auth/accounting/confirmation. Pure policy and executor own
   desired state/guarded intent. Compact measured history is separate from HA
   Recorder. Fable package reads original entities independently. Official latest
   releases checked: HA Core 2026.11.1, Supervisor 2026.11.0; existing matrices
   already include them. Local merge of Fable #32 into this new branch is clean.
2. B: integrated the exact Fable baseline in merge commit `5bac236` (146 tests
   passed unchanged first). Updated four-state/prediction/actual-vs-shadow maps,
   seven views and raw-power freshness/unit availability. Strict sign/threshold
   validation and duplicate top-level metering reject silent misconfiguration.
   Added actual combined HA template/entity contract checks and retained full
   package check_config variants. **1310 full tests passed**, 155 focused
   monitoring tests pass, Ruff lint/format pass. Actual HA awaits CI.
   Controller retains no dashboard import/dependency.
3. C: implemented one bridge authority with expiring status-anchored plans,
   monotonic 15–40 minute bounds, CT-free 30 minute bound, fixed fallback,
   startup reinspection and existing command/auth/backoff/accounting gates.
   Controller and bridge options default false; bridge qualification is separate.
   No token-lifetime claim. 18 new scheduling regressions and 141 focused
   schedule/upgrade/source-boundary tests pass. Full final suite/CI still needed.
   Stage-B actual combined HA and all eight workflows passed at `18fd378`.
4. D: implemented richer measured sessions, meter/model/target cohorts and robust
   whole-day held-out validation (20 complete clean sessions / five days, at
   least ten training and five held-out sessions). Both learning enable and
   hardware qualification default false. Persisted history, verified CT and
   error/coverage bounds are required. A target-specific lower rate is capped
   at nominal/live-watt physics, so it cannot optimistically delay required heat.
   Remaps/model/unit changes clear qualification/cohort authority. Diagnostic
   errors/counts/basis are mapped into the dashboard. Loss/usefulness remain
   explicitly unidentified without independent demand evidence. 30 focused
   learning/history/public-installation cases pass; **1350 full tests pass**,
   Ruff lint/format and both strict mypy targets pass.
   C2 configuration increment implemented before D: actual fresh setup uses HA's
   IANA zone, unverified flat placeholder rates, no forecast/boost authority and
   a 62-degree initial baseline awaiting compliance/appliance verification.
   Existing household settings keep their old values/zone. One tariff model now
   supports editable per-window prices, months, weekday/weekend/shoulder/midday
   windows and zone-specific fixed-standard versus DST clocks. Weekdays without
   an afternoon peak get a configurable service deadline, not an invented peak.
   Optional EMHASS no longer blocks qualified basic CT-free/no-solar control;
   disabled forecasts do not create outage alerts. All command guards remain.
   1342 full tests passed and strict model mypy/Ruff passed; 14 new general
   tariff tests cover zones, seasons, service, no-solar commands and cheap windows.
   Research and unsupported complex products: TARIFFS.md. All eight workflows
   passed for C2 `224c40b` and C `7b775b6`; final-head CI is still required.
5. B2: combined dashboard now reads the controller's verified current tariff
   and prices, including legitimate zero rates, shoulder and seasonal/midday
   windows. The original standalone monitoring-only helper mode remains explicit.
   No-solar/no-household-meter maps generate seven valid read-only views with
   unavailable measurements, not empty entity IDs or invented starting totals.
   163 monitoring tests pass; real HA adds a minimal no-solar check_config case.
   Stage D `1434652` and B2 `f0dd80b` passed all eight workflows.
6. E: commit `d5538d2`; eight real-worker synthetic weeks compare fixed30/fixed60/old-shadow/
   adaptive with CT/no-CT, draws, owner changes, outage/backoff and restart.
   Reproducible JSON and tests conserve energy/service/terminal storage and
   disclose missed targets, unconfirmed peak OFF, prediction and detection limits.
   Removed redundant actual latest-start reads while already storing, preserving
   the old shadow comparison. CT:624 vs740 HTTP (15.7% fewer); CT-free:730 vs713
   (2.4% more). No blanket API/bill saving or real thermal-accuracy claim.
   Bounded history now retains120 rows rather than40 so all three >=20-session
   cohorts can coexist; a restart regression verifies each target independently.
7. F: candidate metadata1.3.15/0.11.0, both bridge changelogs, controller
   changelog, plain README, installation/rollback/tariff/interface/learning/
   simulation guides, completion matrix and independent-review handoff delivered.
   Public distribution/licence administration deferred. Existing secret findings
   are referenced without printing, rotating or rewriting anything.

## Validation checkpoint

Local full snapshot: 1371 tests (Python3.12.14), Ruff lint/format, both strict
mypy targets, compileall, generated-file consistency and Bash syntax pass.
Actual HA/combined package, native image/MQTT/lifecycle and Supervisor checks run
in CI; all eight workflows passed the preceding B2 head `f0dd80b`.
At construction of this final commit, final-head CI still needs verification.
The exact tested SHA and final CI results are recorded in draft PR #35 and the
completion report, avoiding a self-referencing post-CI documentation commit.
Never infer final-head success from an earlier SHA.

## Resolved integration findings

Fable's baseline was integrated by ancestry, then combined mappings, current
verified tariff prices, stale-source availability and optional no-meter views
were corrected locally. Actual HA validates package0/3CT/minimal variants and
renders combined templates/entity registry. One bridge timer owns bounded real
adaptive plans; shadow counts remain separate. Validated target-specific learning
uses persisted provenance and conservative gates, with no hardware authority.

## Resume

Draft PR #35 targets unchanged PR #34. Owner clarification: public distribution
is deferred; no speculative packaging/licence administration. Finish controller,
dashboard, adaptive polling, safe learning and tests first. Add practical common
configuration: HA-default IANA zone, separate local/fixed tariff clock, flat and
editable TOU/shoulder/weekend/midday rates and optional seasonal rows. One tariff
model; limited free/tier/demand/controlled-load/dynamic export products may remain
explicitly unsupported. Remove the unconditional EMHASS activation requirement
for supported basic no-solar operation, preserving every command safety gate.
Retain the closed 45/62/70 set until independent hardware evidence supports more.
Government/network/retailer sources have been researched; document their distinct
roles and conditional offers without copying current prices as defaults.

Implementation A–F is delivered. Verify final-head CI from #35 if resuming,
then obtain independent review and separate owner approvals for merge/live work.
No additional speculative features or public-release administration are needed.
Do not switch/reset existing PR branches or touch Fable's worktree. Retain owner
untracked `review-1b29be1/` and `uv.lock`. Python runtime:
`C:/Users/jacob/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`,
PYTHONPATH = absolute `.test-deps`. Use UTF-8 for text reads/writes.
Do not print the existing application key or historical private-key material.
Independent review and every physical/production approval remain outstanding.
