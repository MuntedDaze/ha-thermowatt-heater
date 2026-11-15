# Requirements completion and remaining gates

This records the preserved PR #35 checkpoint. The current focused phase is in
the [pre-review handoff](../pre-review/HANDOFF.md).

Combined candidate bridge **1.3.15** / controller **0.11.0**, draft PR #35.
Implemented means code and offline evidence exist, not that anything is deployed.
No new runtime feature is commissioned by a test, selector or documentation.
Public distribution is deferred by the owner’s latest scope clarification.

| Requirement | Status | Source / subsystem | Evidence | Specific remaining action |
|---|---|---|---|---|
| Preserve draft checkpoints and Fable isolation | Implemented | Separate `codex/thermann-final-integration`, stacked #35; exact #32 ancestry | Git worktrees/heads, protected anchor table in UPGRADE | Keep #27/#32/#33/#34 unchanged and unmerged |
| Integrated seven-view read-only dashboard | Implemented | `energy_monitoring/` map/package/dashboard/report | 163 monitoring tests; real HA templates/entity registry and check_config CT0/3 + minimal | Owner frontend/actual IDs/statistics review after separate installation approval |
| Closed OFF/45/62/70 protocol, owner hold, persisted intent and bounded confirmation | Implemented | Bridge, `controller.py`, `executor.py`, `targets.py` | Existing transition/auth/guard/command-budget/owner/restart suite retained | Independent safety review and supervised physical qualification |
| Optional generic CT, signed power, W/kW and Wh/kWh | Implemented | `measurement.py`, runtime, raw interface | CT unit/sign/boot/stale/future/cadence/outage tests and measured replay | Commission actual exclusive channel, units/sign and genuine steady-zero reports |
| CT-free baseline and required off-peak storage | Implemented | Runtime + four-state pure policy/controller | No-CT/no-forecast control tests and four week runs | Appliance/tariff commissioning; physical state remains unknown |
| No-solar / no-inverter / no-EMHASS basic tariff control | Implemented | Four-state commissioning guard, config flow/installation defaults | Actual HA activation fixture; general-tariff and no-solar package checks | Configure actual bridge sources, tariff and normal command qualification |
| Peak lockout dominates optional export/forecast | Implemented | Pure policy + controller protective OFF/notification | Peak/DST/restart/cloud-failed-OFF/override and week tests | Real boundary/OFF confirmation review; electrical zero never promised |
| Independent optional-boost enable | Implemented | Settings, native selector, policy | Disabled boost, CT-free and required-only regressions | Owner chooses policy after commissioning |
| Bounded user temperature roles | Implemented | Settings/config/targets + bridge allowlist | Supported/invalid combinations and all allowed transitions | Verify manufacturer/storage hygiene requirements; owner45 is not universal |
| Arbitrary extra setpoints / different heater protocols | Blocked | Closed command allowlist intentionally retained | Rejection tests | Actual vendor/bridge/hardware evidence and explicit safety review before new values |
| HA-default selectable IANA zone and separate tariff clock | Implemented | Config flow, `installation.py`, `model.py`, native settings | IANA/DST/half-hour/season/legacy migration cases + actual HA | Verify actual contract’s clock and household zone |
| Flat / TOU / shoulder / multiple weekday/weekend / midday / monthly seasons | Implemented | One `Tariff` model and validated JSON rows | 14 common-tariff cases; no-forecast price optimisation | Enter verified retail periods/rates; special contract eligibility is not inferred |
| Conditional free/tier/controlled-load/dynamic export/demand charges | Partial | Explicit future quote extension in TARIFFS; no competing pricing engine | Bounds/invalid rows; unsupported cases documented | Interval consumption, circuit/supply evidence, allowance/reset/ratchet/price models before accurate support |
| Network versus retail and Australian source research | Implemented | TARIFFS.md | Government, network and retailer source links | Each user verifies their actual retail contract; no universal rate preset |
| Real adaptive bridge scheduling | Implemented, disabled | `adaptive.py`, `thermowatt_polling.py`, existing bridge timer | 18 focused tests; real worker week replay; image/lifecycle CI | Independent review, actual request/detection baseline, explicit bridge/controller qualification/enables |
| Fixed polling fallback, no auth/backoff/quota weakening | Implemented | Lease/monotonic deadline and existing bridge guards | Lease loss, malformed hints, restart/journal/backoff/confirmation tests | Observe actual cloud failure behaviour only under approved rollout |
| Actual and shadow poll telemetry / request budgets | Implemented | Bridge diagnostics/runtime/sensors, map | Actual HA entity and template checks, source authority guards | Compare real categories and freshness; no token-lifetime assumption |
| Safe history, target/model/meter sessions and held-out fitting | Implemented | `performance.py`, `learning.py`, compact v2 sidecar + Recorder | 30 focused learning/history cases; duplicate/remap/corrupt/gap/held-out tests | Collect real independent complete cycles; this disrupted week qualified zero |
| Conservative learned scheduling rate | Implemented, disabled | Learning gate + `simple_policy.py` target rates | Sufficient-day/error/persistence/CT/hardware/enable gates; conservative starts | Real ≥20 clean sessions/five days per cohort, whole-day holdout and explicit independent hardware approval |
| Accurate real thermal completion / usable shower reserve | Partial | Conditional nominal/calibration range and quality telemetry | Synthetic latest-bound errors reported, not point-accuracy claims | Real draw/stratification evidence; do not promise tank-wide heat from a bottom probe |
| Learned thermal loss and 62→70 useful-demand fraction | Partial | Unidentified in metrics; configured conservative assumptions | Model explicitly reports non-identifiability | Independent no-draw/demand/usable-storage evidence; do not fit confounded effects |
| Economic optimisation / equal-service comparisons | Implemented within model | One policy, 33 strategy cases + eight full-week worker runs | Conserved energy, cost including foregone export, terminal replenishment, misses | Real tariff/forecast/usefulness validation; no annual bill claim |
| Compatible candidate upgrade and rollback | Implemented | Metadata/changelogs, minor5 migration, UPGRADE | Stored option/token/guard/identity and actual HA upgrade/registry tests | Private backup; disabled bridge-first rollout; reconcile62 before old bridge |
| Plain README / install / disable / troubleshooting | Implemented | Root README and current final-integration guides | Local link and generated-file checks | Owner reviews household values and actual frontend |
| Independent review and physical commissioning | Blocked pending evidence | HANDOFF + INSTALLATION | All offline/CI evidence supplied for review | Owner arranges independent review, separately approves live work; no automatic enable |
| Public release / licence / sensitive history remediation | Deferred | Existing redacted findings referenced in HANDOFF | No release, licence, rotation, vendor contact or history rewrite | Only revisit if owner resumes public distribution; prioritise system commissioning |

## What is running

Only development tests/simulations and isolated CI ran. No production component
was installed, no cloud credential was used and no real heater command was sent.
The code supports fixed status/command control after prior qualification, but
this candidate’s physical behaviour is unverified. Adaptive and learned authority
are implemented with separate default-off gates; the old shadow polling comparison
remains advisory. Diagnostic aggregate power and broad completion/calibration
never authorise optional solar. Initial fresh baseline62 is a configuration
starting point awaiting compliance checks, not certified universal safe storage.

## Verification boundary

Local full suite: **1,371 tests**, Python 3.12.14 bundled runtime; Ruff lint/format,
both strict mypy targets, compileall, generated package check and Bash syntax pass.
CI runs Python 3.12/3.13/3.14, actual HA Core 2026.10.4/2026.11.1, native
amd64/aarch64 image/dependency/MQTT/lifecycle/restart/demand tests and Supervisor
2026.10.5/2026.11.0 schemas. Final-head results and exact SHA are recorded on
[draft PR #35](https://github.com/MuntedDaze/ha-thermowatt-heater/pull/35) and the
completion report. Pending/failed CI never qualifies readiness or permits merge.
Actual frontend and hardware behaviour remain separate checks.
