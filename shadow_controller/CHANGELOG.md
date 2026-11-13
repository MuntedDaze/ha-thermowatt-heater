# Thermann Controller (formerly Thermann Shadow Planner)

## 0.9.0 — the simplified three-state controller (owner approval required)

Replaces the 0.4–0.8 planner, economic permission and morning fail-safe with the agreed policy (`simple_policy.py`, [SIMPLIFIED_STRATEGY.md](SIMPLIFIED_STRATEGY.md)). Requires Thermann Hot Water **1.3.13**.

- **Three heater states:** OFF, Manual 45 °C (weekday nights and weekends) and Manual 70 °C. Each command is a guarded bridge payload naming the state it leaves (`<target>@<prior>`), so an app change is never overwritten.
- **Weekday:**
  - EMHASS full-window cost optimisation to reach 70 °C by the soft target (peak − 30 min);
  - starts at once when waiting would miss it, and keeps heating until the peak;
  - pauses only for a later window saving at least $0.30.
- **Peaks:**
  - OFF 2 minutes before every peak, with the command slot before it reserved;
  - measured solar only: 3.3 kW for 10 minutes to start; withdrawal after 5 minutes of import over 0.2 kW or of too little surplus.
- **Weekends:** Manual 45 °C, plus solar Manual 70 °C when at least 1 kW of measured surplus makes it worth it.
- **Setpoint versus achieved:** "70 °C reached" only at a reading of 70 °C.
- **Shadow observation** while automatic control is off: the policy runs and records the command it would send. Nothing is published.
- **Activation and restart** ask the bridge for one guarded status read (used only if the app's on-demand refresh is enabled).
- **Holiday uses dates only.** Departure and return both take effect at 00:00 Hobart local:
  - a departure of today starts Holiday mode at once, and a future one at 00:00 on that date;
  - while active, the guarded controller switches the heater OFF and keeps it OFF;
  - at 00:00 on the return date Holiday mode ends by itself (also across a restart), and the normal policy resumes, usually with Manual 45 °C overnight.

  There is no return target or pre-heating. The two datetime entities are replaced by *Holiday departure date* and *Holiday return date* (`date.thermann_shadow_holiday_departure_date` / `…_return_date`). Saved 0.7–0.8 departure and return times keep their Hobart dates.
- **Removed:**
  - `advisor`, `strategy`, `goals`, `permission`, `control_plan`, `cycles`, `economics` and `decision`;
  - the model's planner (`evaluate`);
  - minimum heating and rest;
  - the comfort reserve and latency reserve;
  - the unexplained-heating hold.
- **New setting:** *Three-state commands qualified (1.3.13)* (System, locked while control is on). Automatic control cannot be enabled until it is on.
- **Retired** (values kept, entities removed): the morning and afternoon planning settings, storage target, margins, cycle and gap timers, base-load source, minimum heating and rest, latency reserve, and the T3 qualification switch. The planner's sensors are removed from the registry; measurement, tariff and controller entity IDs are unchanged. New policy sensors are added.
- **Fixed during integration testing:** while a command awaited confirmation, the policy planned from the old state and could ask for it back straight after the confirmation. It now plans from the requested state, and the controller enforces the 15-minute spacing itself as a backstop.
- **Tests:**
  - `test_controller_0_9_0.py`;
  - `test_integration_0_9_0.py`: HA states, EMHASS and the GoodWe meter → runtime → policy → controller → real bridge 1.3.13 → mocked cloud → confirmation. It covers shadow, live, owner change, restart, commissioning, holiday, 12hr Override and the dashboard values.

## 0.8.0 — names and a simpler settings interface (development)

- **Thermann Controller** is the integration's display name (was Thermann Shadow Planner / Hot Water Controller); the app is **Thermann Hot Water** (app 1.3.12). Both are labelled unofficial community software, not Thermann products.
- **12hr Override** replaces "guest mode" in every label and alert. Behaviour unchanged: Manual 70 °C for 12 hours regardless of price, end time shown, cancel any time, normal control afterwards, every safety rule kept.
- **Nothing to reinstall:** same domain (`thermann_shadow`), device, entry, entity IDs (renamed entities keep their old IDs; fresh installs get the same IDs), MQTT topics, saved settings and stored controller state. The config entry and device are renamed in place.
- **Settings in three groups:** Everyday, Advanced, System. 15 settings with no production effect are retired from the interface; their stored values stay. Their entities and the long-orphaned 0.3.0/0.5.0 entities are removed from the registry instead of showing as unavailable.
- **Configure is a menu:** Comfort, tariff and forecast settings / System and commissioning / Sensor mappings.
- The dashboard is titled **Hot Water**.

## 0.7.1 — settings safety and validation (development)

From the settings audit ([SETTINGS_AUDIT.md](SETTINGS_AUDIT.md)). No change to the two commands, the bridge allowlist or stored controller state.

- **Locked while automatic control is on:** command topic, T3 qualification, dwell, command and request budgets, confirmation timeout, latency reserve, meter sign and verification, the tariff contract, freshness limits and sensor mappings. Turn control off to change them. Preferences, notifications and Restore recommended still apply at once.
- **Command topic must match the mapped heater** (`command_topic_does_not_match_heater` otherwise).
- **No command unless the bridge app's `command_policy` is `automation`.**
- **Validation:** notification service name format; whole-number budgets; minimum rest at most latency + 30 min (max 90); poll age 35–90 min; forecast age 35–360 min; prices 0–2 $/kWh. Rejections now say which rule failed.
- **Restore recommended** no longer changes dwell, budgets, timeouts or freshness limits.
- Pricing or planning setting changes also reset the economic-permission samples and timers.
- *Pause shadow planning* no longer affects an active controller (use Hold or the master switch).
- Descriptions corrected for settings that do drive production planning (solar start qualification, minimum cycle and gap).
- Config entry 1.2 → 1.3: values outside the new ranges move to the nearest allowed value, each logged. A 0.7.0 rollback still loads the entry.
- The master switch shows whether the notification service exists.

## 0.7.0 — economic permission, morning 45/42, guest and holiday modes, thermal observer (development)

- **Economic heating permission** (`permission.py`): Manual stays permitted while heating now would be economical (meter-priced, excluding the element's own load), and parks when not. It stays on after thermostat satisfaction; solar-justified permission continues across the peak start; afternoon storage never buys peak-grid heat; an economic park during a peak bypasses minimum heating (not minimum rest).
- **Morning:** preferred **45 °C by 06:00** and hard **42 °C by 07:00**, every day (new settings: preferred time, hard time, preferred reserve; the minimum stays `morning_threshold_c`). One cooling allowance protects the hard minimum. Fail-safe permit when the planner or meter is unavailable before 07:00. The legacy morning and shower settings are kept but hidden.
- **Guest mode** (12 h) and **controller-managed holiday mode** (return-ready), with new buttons, datetimes and sensors. Native Thermann Holiday is not used.
- **Read-only thermal observer:** tank state with confidence, suspected draws, cooling spans, heating performance and predicted versus actual. It never affects control.
- **Fix found in the Stage C preflight (present since 0.5.0):** with automatic control on, the shadow-era "native Schedule expected" check still ran, so a heater in Manual or OFF (the controller's own states) gated the planner as *owner review required* and the controller would only ever have held, parked for peaks or used the morning fail-safe. The check and the intervention latch now apply only while control is off. Closed-loop tests had supplied the plan directly, so they did not see it; a runtime-level regression test now covers it.
- **Unchanged:** 30-minute polling, the two commands, the bridge allowlist, command and request budgets, confirmation, owner override, disabled by default.

## 0.6.2 — bounded confirmation for a late cloud readback (bridge 1.3.11)

- **Why.** T3b: the bridge's only read right after the POST still showed the
  old mode although the heater went OFF. 0.6.1 would have waited for a
  background poll and locked if that poll was ≥5 minutes later and still old.
- **Requires bridge 1.3.11** (`bridge_1_3_11_required` otherwise). Its
  `awaiting_confirmation` and `submitting` are in progress: no status seen
  meanwhile is taken as an outcome, and the old 5-minute late-poll rule no
  longer applies while the bridge is still deciding.
- `not_confirmed_within_limit` → `fault_locked` (`command_not_confirmed`) with
  guidance (sent once, not repeated; check the app; Acknowledge).
  `unexpected_state_after_command` → owner override.
- New gate `bridge_confirmation_pending`: no command while the bridge awaits
  any command's outcome (for example one published by hand).
- Unchanged: two commands, OFF target rule, 70 °C confirmation, dwell, daily and
  request budgets, latency reserve, peak guard, protective heating, persisted
  intents, no retry, restart reconciliation, disabled by default. No option is
  added, removed or migrated.
- Real-HA CI adds the 0.6.1 → 0.6.2 upgrade (frozen copy of `1324a3c`, identical
  to the installed files). The compatibility test against the real bridge 1.3.11
  code adds delayed readback (old mode first, requested mode at either
  follow-up), no confirmation, an owner change and a bridge restart mid-window.

## 0.6.1 — commands between polls with bridge 1.3.10; owner changes found at command time

- **Requires bridge 1.3.10** (PR #15). It reads OFF correctly (`Cmd` 8, seen in
  T3) and reads status once before a command when its status is older than
  60 s. A bridge without that support is never commanded
  (`bridge_1_3_10_required`).
- **No more poll-slot wait.** 0.6.0 published only within 35 s after a poll;
  0.6.1 publishes when the planner decides. New gates: `heater_status_too_old`
  (no status for more than a poll interval + 5 min) and
  `bridge_refresh_budget_exhausted` (the bridge's 24 refreshes a day used up;
  clears at the next poll).
- **Owner changes found by the bridge.** `already_in_requested_state`,
  `refused_mode_mismatch` and `refused_target_mismatch` now mean owner override
  (nothing was written), not a fault. While the bridge reports
  `refreshing_status` or `submitted_awaiting_status`, a new status is not taken
  as the outcome, so the pre-command read is never mistaken for confirmation.
- **Every other bridge refusal** (`dropped_*`, `refused_*`, `rejected_*`,
  including new and future codes) locks with `bridge_refused_or_dropped`, never
  retried.
- Unchanged: two commands only, OFF target rule, dwell, 6 commands a day with
  2 for comfort, 220 requests a day, latency reserve (30 min), peak guard,
  protective heating never interrupted, persisted intents, no retry, restart
  reconciliation, disabled by default. No option is added, removed or migrated.
- Real-HA CI adds the **0.6.0 → 0.6.1** upgrade from the installed version.
  A compatibility test drives the real bridge 1.3.10 code with the controller
  (runs once the bridge code is in this tree; verified locally).

## 0.6.0 — control architecture corrected: Manual 70 °C permit / software OFF park

- **Why the change.** The owner's app testing showed that an empty native
  Schedule made the app's setpoint revert to 40 °C, so it cannot be the parked
  state. Software OFF keeps 70 °C, and the owner's guide confirms antibacterial
  and frost protection stay active in OFF.
- **New method:**
  - the controller now parks with `off` and resumes with the guarded
    `Manual:70`; these are its only two commands, and they match the bridge
    1.3.9 `command_policy: automation` allowlist;
  - OFF reporting 70 or no usable setpoint allows a resume; a usable other
    target means owner override (never silently reset to 70);
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
