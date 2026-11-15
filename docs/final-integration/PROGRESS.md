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
simulations and release/commissioning documentation. No main/protected-branch
merge, installation, real Thermann/MQTT/authentication, heater operation,
credential/history rewrite, licence selection or release publication.
New draft PR will target `codex/economic-dual-storage` (PR #34).

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
   Stage D `1434652` passed all eight workflows. E replay is still in progress.
6. E: comparative polling and full-week end-to-end scenarios including owner,
   restart, cloud/meter failures, CT-free and CT-measured; equal service/terminal
   energy, request categories and detection/error trade-offs must be explicit.
7. F: compatible candidate metadata, plain-language docs, existing security
   findings and future owner rollout plan, requirements matrix and independent-review
   handoff. Full local suite and all applicable final-head CI required.

## Targeted integration findings

- Fable maps still describe the 0.9.1 baseline and omit already available
  completion/poll/learning/62-degree telemetry. Update only the combined branch.
- Fable's HA workflow validates the monitoring package alone. Add combined
  component/package/template/entity checks without external networking.
- The bridge has one clock-aligned poll timer; shadow suggestions currently have
  no actuation interface. Extend this authority rather than adding a cloud loop.
- Existing command/status freshness must not be silently relaxed by adaptive
  scheduling. Anchor hints to actual successful status; advance consequential
  reads, reuse confirmation and fall back if the controller/lease is absent.
- Learning records lack session/error/validation detail and held-out gating;
  nominal model remains the only scheduling authority until real gates pass.
- Reassess power-source freshness and strict map validation: numeric stale
  sensors currently remain available to derived monitoring energy even though
  Health reports staleness. Do not hide outages as zero measurements.

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

Inspect branch/status first. Do not switch/reset existing PR branches or touch
Fable's worktree. A–D are delivered. Finish E/F, commit logical increments and
push only draft PR #35's integration branch. Python runtime:
`C:/Users/jacob/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`,
PYTHONPATH = absolute `.test-deps`. Use UTF-8 explicitly for text reads/writes.
Do not print the existing application key or historical private-key material.
Independent review and all physical/production gates remain outstanding.
