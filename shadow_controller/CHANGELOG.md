# Thermann Shadow Planner

## 0.6.0 — control architecture corrected: Manual 70 °C permit / software OFF park

- **Why the change.** The owner's app testing showed that an empty native
  Schedule made the app's setpoint revert to 40 °C, so it cannot be the parked
  state. Software OFF keeps 70 °C, and the owner's guide confirms antibacterial
  and frost protection stay active in OFF.
- **New method:**
  - the controller now parks with `off` and resumes with the guarded
    `Manual:70`;
  - OFF's reported setpoint is never used to classify, permit or confirm;
  - a resume is confirmed only at Manual **70 °C**;
  - Schedule, Eco and Holiday are owner control.
- **Protective heating** while OFF is never interrupted, and no command is sent
  while it runs.
- **Commissioning:** the empty-Schedule confirmation and stage are removed. No
  native Schedule configuration is required. Clock and native-fallback warnings
  apply only while the programme is in use.
- **Bridge:** requires **bridge 1.3.9** (PR #12). It handles an OFF status with
  an out-of-range setpoint, which 1.3.8 rejects, and accepts the guarded resume
  from OFF.
- **Tests:** 879, including 90 controller tests (17 new OFF tests and closed
  loops with an antibacterial cycle during OFF). The real-HA check now resumes
  from OFF.
- **Documentation:** version-neutral CONTROLLER, COMMISSIONING and
  PRODUCTION_READINESS, plus UPGRADE_0_5_0_TO_0_6_0.

## 0.5.0 — production controller candidate (not deployed; control off by default)

- **Control method.** Manual 70 °C permits heating, and the empty weekly
  Schedule parks it (owner decision; T1 passed in the official app).
- **Controller.** A new controller (`controller.py`, `control_plan.py`,
  `executor.py`) provides:
  - an explicit state machine;
  - persisted unique intents;
  - one poll-aligned guarded command (`Manual:70` via bridge 1.3.9, or
    `Auto`), never retried;
  - confirmation from observed status and the bridge's `last_command`;
  - restart reconciliation without re-sending;
  - owner precedence, with Hold, Resume and Acknowledge;
  - dwell, daily-command (with a comfort reserve) and cloud-request budgets;
  - the hysteresis gate;
  - unexplained heating never interrupted;
  - notifications with cooldown and a restoration notice.
- **Planner:** in controlled mode, comfort deadlines are planned 30 minutes
  early (the execution latency reserve), and readiness reports
  `planned_by_controller`.
- **Bottom-sensor overshoot cap:** start reading plus delivered energy, for
  90 minutes after heating.
- **Peak guard:** parks at the last slot before a peak unless the element is
  heating for comfort. This was found by replaying the 10 Nov history.
- **Empty native Schedule** (`[]`) is accepted. With it, the heater-clock DST
  warning and "native programme is the comfort fallback" are not raised. The
  protective-heating warning remains, and so does a warning that nothing heats
  ordinarily while control is off. A non-empty programme keeps its clock
  warnings.
- **Disabled controller is silent:** no notifications, and controller state is
  written only when it changes.
- **Fresh installs cannot command:** the master switch refuses to turn on until
  the command topic and both commissioning confirmations are set.
- **Tests:** 62 new controller tests, including:
  - the real 1.3.8 bridge;
  - a model of the 1.3.9 contract;
  - closed-loop days through the real advisor;
  - winter, weekend, DST and forecast-error cases.

  A real-HA wiring check captures the MQTT message without sending it, and the
  replay tool gains `--controller-dry-run`.
- **Documentation:** CONTROLLER, COMMISSIONING (Stages A–E),
  PRODUCTION_READINESS, LOCAL_CONTROL_FEASIBILITY.

## 0.4.0 — Stage 3a read-only candidate

- Fix the false-stale defect: cloud readings are fresh by the bridge poll
  timestamp. HA MQTT entities do not rewrite identical payloads, so 0.3.0 was
  blocked most of the time. A retained status after an HA restart keeps its real
  poll time.
- Read-only heater element ON/OFF/UNKNOWN estimator with confidence and basis
  (`WaterHeaterSts` bit 0 as empirical evidence, 3 kW load steps, masked
  switch-off and stale-bit handling, optional heater CT). Base household load
  excludes the real element exactly once.
- Dynamic readiness deadlines from the tariff's actual peak starts (07:00/08:00
  morning, 16:00/17:00 evening by season), weekend household times, optional
  earlier shower time. Morning threshold **42 °C**; a saved untouched 40 °C is
  migrated (entry 1.2).
- Incremental-cost strategy engine: 15-min slots, exact optimiser over ≤3 blocks
  with per-deadline energy, heat-now as a minimum-cycle start, fallback with
  allowance, waiting only for ≥5 c/kWh of heating moved, decision stabiliser,
  thermostat-satisfied handling, meter pre-commissioning detection.
- AC PV, combined 5 kW AC clipping, two-way bounded measured correction (clipped
  readings are a lower bound).
- Native Schedule outlook and a read-only Schedule advisor.
- New sensors (heater state, base load, surplus, tariff change, readiness,
  saving, confidence, native cost, Schedule advisor). Four meaningless simulation
  counters retired. Dashboard rebuilt.
- Real-history replay tool (local recorder copy, read-only), frozen 0.3.0 vs
  0.4.0 comparison, 46 new tests, real HA 0.2.0→0.4.0 and 0.3.0→0.4.0 upgrade
  checks and an unchanged-MQTT freshness check. The legacy closed-loop day
  harness (it simulated a non-existent executor) was retired.


## 0.3.0 — Phase 2B shadow-only review candidate

- Optional forecasts read from HA states only: EMHASS `forecasts` lists (custom
  entity keys, string values), buffered Forecast.Solar `watts` (overnight gaps
  are zero solar) and a flat measured household baseline. Explicit W/kW and real
  generation time are required; stale, pre-restart or malformed data falls back.
  PV −25 %, load +25 %, +0.3 kW household allowance; a 15-minute measured PV mean
  can only reduce the forecast, fading out over 3 hours.
- Partial-surplus economics: a full 3 kW element, imported energy plus foregone
  feed-in, continuous cycle now vs the best feasible later cycle across tariff
  boundaries. Solar headroom applies to measured surplus only. The independent
  off-peak fallback is reserved regardless of forecasts and starts when due.
- Stateful ideal-energy cycle simulation: 10-minute start qualification,
  20-minute loss grace, 30-minute minimum cycle and gap, AUD 0.10 switching
  benefit. Comfort, data gates and protections take precedence. The heating-time
  allowance moves starts earlier and is not simulated as extra heat.
- Plain-language decisions: heat now (solar / partial solar / riding through
  cloud), grid fallback, insufficient time, wait for solar, wait for planned
  window, forecast unavailable, no heating needed, data unavailable, owner review.
  New *Decision code* and *Forecast usable solar before deadline* sensors.
- 39 native settings controls and Configure share one options store with atomic
  validation; current/recommended/original values with explanations. The stored
  custom tariff table is validated in every tariff mode. Restore recommended keeps
  the tariff contract, mappings, verifications, meter direction, pause state and
  native references, and can be undone once.
- Redesigned native-card dashboard (sections layout) with a large colour-coded
  recommendation, tank gauge, plan, costs, power, history, Settings and
  Diagnostics views.
- Tests: offline economics/forecast/cycle/decision/restore regressions, 23
  reproducible closed-loop synthetic days, and real HA Core checks of every
  settings entity via services, dashboard references/templates, forecast paths and
  a genuine 0.2.0 → 0.3.0 upgrade over persisted storage. The Thermowatt 1.3.8
  directory is unchanged; nothing targets the heater, Schedule, MQTT or cloud.

## 0.2.0 — confirmed-owner Phase 2A candidate

- Fix Add Integration discovery by classifying the integration as a hub. Copy
  immutable source mappings before exposing diagnostic attributes. Test actual
  WebSocket state/event serialization and Recorder attribute/SQLite storage paths
  on isolated Home Assistant Core, including a mappingproxy negative control.

- Documentation/source review clarifies manufacturer app On/Off hygiene support,
  missing API resume/retention evidence, outages, bounded future cycles and shadow
  installation. Add mocked source-contract tests; no runtime/version change.

- Continue the existing planner/PR; retain the read-only boundary and all bridge
  files at v1.3.8. No deployment or automatic merge.
- Use confirmed Aurora 93 prices and fixed AEST periods, verified export-positive
  meter defaults, editable morning 40°C threshold and afternoon 70°C target.
- Prefer sustained net-export opportunities and latest suitable off-peak backup;
  reserve full backup independently of optional forecasts. One-minute LOCAL
  sampling adds no cloud requests; require a ten-minute export hold by default.
- Add current tariff/price, targets, source, latest-start and device-clock reminders;
  distinguish summer peak deadlines from nominal comfort and weekend goals.
- Update control/recovery design for accepted manual outage recovery, document the
  missing verified stop/resume contract and unestablished factory-reset procedure.
- Extend offline scenarios, HA settings/reload tests and all bridge regressions.

## 0.1.0 — Phase 2A owner-review candidate

- Separate Home Assistant sensor integration with editable entity mappings and
  settings, owner-reported defaults, local five-minute evaluation and a built-in
  card dashboard. No EMHASS/runtime dependencies beyond Home Assistant.
- Hardcoded shadow-only capability: no services, heater controls, MQTT writes,
  network clients, refresh triggers, lockout resets or native schedule changes.
- Explicit measured/estimated/unverified separation; fixed safe decision codes,
  fresh post-restart inputs, cloud-health gates and native-intervention review.
- Provisional export-positive HK1000 sign remains unvalidated by default. Actual
  tariff/DST/weekend settings require confirmation; no published price assumed.
- Uniform 315 L / 3 kW scenarios, deadline shortfalls, net-export opportunities,
  cheap tariff windows and foregone export costs; no inferred usable reserve,
  energy measurement, hygiene status or confirmed element energisation.
- Display observed local request growth; include the 3-attempt refresh/replay
  pattern in illustrative usage estimates, without inventing quota/reset times.
- Offline scenario tests and isolated real HA Core config-flow/lifecycle checks.
  Thermowatt add-on stays 1.3.8 with all bridge files and protections unchanged.
