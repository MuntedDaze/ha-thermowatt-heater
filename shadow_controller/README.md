# Thermann Shadow Planner 0.4.0 (candidate)

> **0.5.0 production controller candidate:** see [CONTROLLER_0_5_0.md](CONTROLLER_0_5_0.md),
> [COMMISSIONING_0_5_0.md](COMMISSIONING_0_5_0.md) and
> [PRODUCTION_READINESS_0_5_0.md](PRODUCTION_READINESS_0_5_0.md). Automatic control is
> **off** and impossible until commissioning (Stages B and C) is complete; everything
> below describes the planner, which the controller follows.


A **shadow-only** hot-water planner for the Thermann 315 L / 3 kW heater. It reads
existing Home Assistant entities, decides when heating *would* be best, and
explains why on a dashboard. **It never operates the heater.** The native
Schedule keeps controlling the real element. Draft PR #9; owner review required,
no merge or deployment is authorised.

Priorities, in order: **manufacturer safety, hot-water readiness, minimum total
electricity cost (including foregone feed-in), solar self-consumption when cost is
equal, fewer switches.**

- [Stage 3a / 0.4.0 changes and evidence](PHASE3A_0_4_0.md) and
  [0.3.0 vs 0.4.0 comparison](COMPARISON_0_3_0_VS_0_4_0.md).
- [Upgrade 0.3.0 → 0.4.0](UPGRADING_0_4_0.md) — owner steps, verification, rollback.
- [Stage 3b/3c proposal](STAGE_3B_3C_PROPOSAL.md) — forecasts, whole-home solar
  advisor, Tapo appliances, notifications, wall-tablet dashboard (design only).
- [Upgrade or install 0.3.0](UPGRADING_0_3_0.md) — previous version.
- [Forecast setup](FORECAST_SETUP.md) — EMHASS / Forecast.Solar / baseline.
- [Phase 2B design and review](PHASE2B.md) — economics, cycles, decisions, tests.
- [Legacy 0.3.0 cloud-interruption cycle results](CYCLE_SCENARIO_RESULTS.md).
- [Control and recovery](CONTROL_AND_RECOVERY.md), [native On/Off review](NATIVE_ON_OFF_REVIEW.md)
  and [supervised qualification plan](SUPERVISED_VALIDATION.md) — future control only.

## Safety boundaries

- No heater commands, MQTT writes, HA service calls, network clients, cloud
  refreshes, authentication changes or quota resets. No option enables control.
- The Thermowatt add-on stays **1.3.8**, byte-identical, with commands and
  on-demand refresh disabled. Native Schedule and T-Comfort are never changed.
- A fixed one-minute **local** timer re-reads HA states. The planner adds **zero**
  Thermann requests; forecast updates add none either.
- Simulated heating is labelled hypothetical everywhere. Physical element state,
  On/resume and safe Off remain **unqualified**.

## What it reads

| Input | Default entity | Use |
|---|---|---|
| Heater temperatures | `water_heater.home_boiler_home` attributes | bottom-sensor temperature, reported target |
| Mode, poll time, health | `sensor.home_boiler_home_vendor_mode`, `sensor.home_last_successful_poll`, `sensor.home_cloud_health` | gates; native mode/target change latches *owner review* |
| Request counter | `sensor.home_cloud_request_attempts_local_lifetime` | diagnostics only |
| Net grid power | `sensor.goodwe_inverter_meter_active_power` | **primary measurement** of surplus; positive = export (owner load-tested) |
| PV, house load | GoodWe PV / house consumption | display; PV also corrects forecasts |
| Forecasts (optional) | none | see [Forecast setup](FORECAST_SETUP.md) |

Missing, stale (poll > 45 min, meter > 120 s), restored or unhealthy inputs
suspend the recommendation (**DATA UNAVAILABLE**). The native Schedule remains
the real comfort fallback. Cloud-read time is not a device sample time.

## How it decides

The thermal estimate is `315 × 4.186 × rise / 3600 ≈ 0.3663 kWh/°C` (about 7.3 min
per °C at 3 kW). It uses the vendor reading `T_Avg` directly. That is a planning
reading, not a whole-tank reserve, and not the thermostat's own control
temperature.

- **Morning:** **42 °C** reading before the morning peak starts: 07:00 standard
  time, **08:00 daylight time** on weekdays, derived from the tariff table itself.
  An optional earlier shower-ready time can only make it earlier. Weekends use a
  household time (default 08:00). **Never a 42 °C storage setpoint.**
- **Afternoon:** 70 °C (65–70 °C) before the evening peak: **16:00 standard time,
  17:00 daylight time**. Weekends use a household time (default 16:00). If the
  native thermostat switches the element off inside a permitted window, storage
  counts as ready (its own sensor reached the target) until the reading falls >5 °C.
- **Requirements** are cumulative from now and include an assumed standing loss
  (0.2 °C/h) and morning draw (10 °C). Both are editable assumptions, not
  measurements.
- **Actual heating:** the element state is estimated ON / OFF / UNKNOWN from
  `WaterHeaterSts` bit 0 (empirical) and 3 kW load changes. **Base household load =
  house − 3 kW while ON**, so the real heater is never counted twice.
- **Cost:** extra cost of running the fixed 3 kW element, relative to not running
  it, per 15 minutes:
  `hours × [0.09276 × s + rate × (3 − s)]`, with s = min(3, AC PV − base load).
  For example, 1 kW exported → 43.3 c/h off-peak, 81.7 c/h peak; 2 kW surplus →
  35.6 c/h off-peak versus 51.1 c/h all-grid.
- **Plans compared** (all deliver the same energy by each deadline):
  - heat now (for at least the 30-min minimum cycle);
  - the best plan overall (≤3 blocks);
  - the best single block, and the best single block later;
  - a fallback start that keeps the 30-min allowance.
- **Waiting** is recommended only if it saves at least **5 c per kWh** that would
  be heated now and the fallback stays viable. Without a qualified forecast,
  future solar is assumed zero, so waiting is never based on hoped-for sun.

Recommendations shown in large type:

| Label | Meaning |
|---|---|
| HEAT NOW | heating now is the cheapest plan, solar is available and waiting saves too little, or the comfort fallback is due |
| HEATING NOW / HEATING LIKELY (NATIVE) | the native Schedule is heating (LIKELY = medium confidence); the text says whether that matches the cheapest plan |
| WAIT – CHEAPER LATER | a later plan saves at least the threshold; saving, start and latest safe start shown |
| NO HURRY | no meaningful cost difference; heat before the stated latest start |
| NO HEATING NEEDED | both goals met (or storage satisfied by the native thermostat) |
| INSUFFICIENT TIME | even continuous heating cannot meet the goal; shortfall shown |
| DATA UNAVAILABLE / OWNER REVIEW / PAUSED | gates; nothing is recommended |

Only changes between optional economic choices must persist 10 minutes. The physical
heater state, comfort, data gates and "no heating needed" apply immediately.
Readiness describes what the native Schedule is predicted to achieve, never a
hypothetical plan.

## Tariff (owner-confirmed Aurora 93)

| Item | Default |
|---|---|
| Peak import | AUD 0.361878/kWh |
| Off-peak import | AUD 0.170200/kWh |
| Export compensation | AUD 0.092760/kWh |
| Weekday peaks | 07:00–10:00 and 16:00–21:00 **fixed AEST (UTC+10)** |
| Weekends | off-peak all day |

Hobart daylight saving is handled automatically: peaks display at 08–11 and 17–22
in summer. Never shift times manually for DST. Rates, peak times and weekend
policy are editable; arbitrary weekly periods use custom mode in Configure. The
stored custom table is always validated, even in Aurora mode. The Thermann
device clock is separate and needs a manual DST check (Diagnostics reminder).

## Dashboard and settings

`dashboard.yaml` (native cards only) has three views:

- **Hot Water** — colour-coded recommendation with explanation, tank gauge,
  targets and countdown, next hypothetical start/completion, fallback time,
  energy/cost estimates, live power and prices, forecast surplus, heat-now-vs-later
  costs and history graphs. Sections layout reflows to one column on phones.
- **Settings** — every preference as a native number/time/select/toggle in four
  groups (Comfort, Solar & Forecasting, Heating Cycles, Advanced), each with its
  **current, recommended and original** value and a plain explanation. The
  controls and Configure share **one** saved configuration; changes validate
  atomically, recalculate locally at once and never reload or contact the heater.
  **Restore recommended** (confirmed) resets preferences only — tariff contract,
  mappings, verifications, meter direction, pause state and native references are
  kept — and **Undo last restore** puts the replaced values back once.
- **Diagnostics** — measured inputs vs estimates, forecast source/age/error and
  correction, simulated cycle details, reasons, warnings, native references and
  request accounting.

## Cloud accounting

30-minute polling is about 48 bridge cycles a day. One cycle can be
status → token refresh → replay (3 attempts), so ~144 attempts/day is plausible.
This is not a vendor quota or upper bound. The counter is the bridge's local
lifetime attempts and excludes the official app.

## What is verified, and what is not

Verified in isolated CI (no network): real HA Core 2026.10.4 and 2026.11.1
config/options flows, every settings entity driven through the HA service layer,
restore/undo, atomic rejections, all dashboard entity references and rendered
templates, forecast-present/invalid paths, WebSocket and Recorder serialisation,
reload/unload, and a genuine **0.2.0 → 0.3.0 upgrade** over persisted HA storage.
Offline tests cover economics, cycles, forecasts, DST and 23 closed-loop days.

Not verified: the owner's real dashboard rendering on desktop/phone, real-data
forecast accuracy, the owner's actual EMHASS/Forecast.Solar entities, the real
thermal response and any physical heater control.
