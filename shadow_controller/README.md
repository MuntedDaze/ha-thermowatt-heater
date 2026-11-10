# Thermann Shadow Planner 0.3.0

A **shadow-only** hot-water planner for the Thermann 315 L / 3 kW heater. It reads
existing Home Assistant entities, decides when heating *would* be best, and
explains why on a dashboard. **It never operates the heater.** The native
Schedule keeps controlling the real element. Draft PR #9; owner review required,
no merge or deployment is authorised.

Priorities, in order: **comfort first, maximise solar second, minimise cost third.**

- [Upgrade or install 0.3.0](UPGRADING_0_3_0.md) — safe owner steps.
- [Forecast setup](FORECAST_SETUP.md) — EMHASS / Forecast.Solar / baseline.
- [Phase 2B design and review](PHASE2B.md) — economics, cycles, decisions, tests.
- [Closed-loop day scenarios](DAY_SCENARIO_RESULTS.md) and
  [cloud-interruption cycle results](CYCLE_SCENARIO_RESULTS.md) — reproducible.
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

The thermal estimate is `315 × 4.186 × rise / 3600 ≈ 0.3663 kWh/°C`, about
7.3 minutes per °C at a full 3 kW. It uses the bottom sensor directly; it is not
a whole-tank reserve or a hygiene measurement.

- **Morning comfort:** 40 °C by 07:00 Hobart (both editable). At or above the
  threshold no morning heat is planned. 40 °C is a decision threshold, **never a
  storage setpoint**. Example: 35→40 °C ≈ 37 ideal minutes, so heating is planned
  to begin by about 05:53 with the 30-minute allowance.
- **Afternoon storage:** 70 °C by default (65–70 °C, never silently reduced).
  On weekdays the deadline is the actual evening peak: 16:00 Hobart in winter,
  17:00 in daylight time (Aurora Tariff 93 is fixed AEST). The editable 16:00
  comfort time is shown separately and is the weekend deadline.
- **Heating time allowance** (30 min) moves start times earlier; it is not extra
  heat. A full off-peak **grid fallback** is reserved independently of forecasts
  and starts when due, whatever the forecast says.
- **Partial solar counts.** The element is always a full 3 kW load. With 2 kW
  surplus, 2 kW is self-consumed and 1 kW imported: one hour costs
  `2 × 0.092760 + 1 × 0.170200 = AUD 0.3557` including foregone feed-in, versus
  `AUD 0.5106` all-grid off-peak. Costs compare a continuous cycle now with the
  best feasible later cycle, minute by minute across tariff boundaries.
- **Stable cycles:** an optional start needs 10 minutes of sustained advantage
  and a 30-minute gap since the last cycle; an optional stop needs 20 minutes of
  sustained disadvantage after at least 30 minutes of running; the advantage must
  exceed AUD 0.10. Comfort, data gates, protections and owner action override
  these optional timings.

Recommendations shown in large type:

| Label | Meaning |
|---|---|
| HEAT NOW | solar covers the element, partial solar beats the grid alternative, or a cycle rides through a short cloud |
| GRID FALLBACK | the reserved fallback is due: heat to protect the deadline |
| INSUFFICIENT TIME | even heating continuously from now cannot reach the goal; shortfall shown honestly |
| WAIT FOR SOLAR | a useful surplus is qualifying, or a qualified forecast shows a cheaper solar window |
| WAIT FOR PLANNED WINDOW | no worthwhile advantage now (or forecast unavailable); fallback reserved |
| NO HEATING NEEDED | the goal is already met |
| DATA UNAVAILABLE / OWNER REVIEW / PAUSED | gates; nothing is recommended |

Each comes with a plain-language explanation containing the numbers used.

**Important default behaviour:** without a forecast only 15 minutes of measured
surplus is credited, which caps a solar start's advantage at ≈ AUD 0.058 —
below the AUD 0.10 threshold. With forecasts off the defaults therefore usually
wait for the fallback, and Diagnostics says so. See
[Forecast setup](FORECAST_SETUP.md#why-forecasts-matter-with-the-default-switching-threshold).

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
