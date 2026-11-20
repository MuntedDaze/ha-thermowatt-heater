# Thermowatt operating policy

**This is the authoritative requirements document** for the Thermann
Controller (`custom_components/thermann_shadow`) and the Thermann Hot Water app
(`thermowatt-heater`). If any other document, setting, default, test, fixture
or comment disagrees with it, this document wins and the other item is a defect
or a historical record.

| | |
|---|---|
| Applies to | Controller 0.18.1 and Thermann Hot Water app 1.5.0 onward |
| Last owner decision | 20 November 2026 |
| Temperature decision record | [decisions/HOT_WATER_TEMPERATURE.md](decisions/HOT_WATER_TEMPERATURE.md) |
| Audit behind this document | [audits/2026-11-20/](audits/2026-11-20/README.md) |
| History (not requirements) | [history/](history/README.md) |

**Objective (owner, 20 November 2026).** Minimise electricity cost, maximise
genuine solar self-consumption, maintain adequate hot water, and keep the
system reliable, predictable and safe. Intelligence improves those
fundamentals; it is never a dependency for basic heating.

**Implementation status.** §2 describes Controller 0.18.1 and app 1.5.0. The
owner's installation runs Controller 0.17.1 / app 1.4.1 until the supervised
in-place upgrade ([docs/owner/UPGRADE.md](owner/UPGRADE.md)).

The document has three parts: **1. Policy** (what the owner requires),
**2. Implementation** (how the code meets it, with source locations) and
**3. Rules for changing this system**.

---

## 1. Policy

### 1.1 Superseded requirements

The following earlier requirements are **cancelled** and must not be
reintroduced from old settings, defaults, parser structures, validation,
documents, fixtures or tests:

- **Morning reserve: 45 °C by 06:00 (preferred) and 42 °C by 07:00 (hard)**
  (0.7.0). Cancelled 20 November 2026. There is no morning temperature target,
  no morning top-up, no morning deadline and no morning alarm.
- The 0.4–0.8 economic planner (afternoon 65–70 °C storage target, morning draw
  and standing-loss assumptions, minimum cycle/rest/latency periods, switching
  benefit). Replaced by the simplified policy in 0.9.0.
- The native Thermann Schedule references and T-Comfort reference.
- The weekend 15-minute PV qualification and low-PV "sunset" early end
  (replaced in 0.17.0).
- Pre-Smart adaptive polling (v1/v2 plans), the polling preview and the
  controller's own polling-mode choice (replaced by one Smart configuration in
  0.18.0 / 1.5.0).

### 1.2 Heating targets

| Target | Use |
|---|---|
| **Manual 45 °C** | Overnight baseline every day, and weekends until the comfort window opens |
| **Manual 62 °C** | Normal weekday storage; weekend comfort window; 12-hour Override |
| **Manual 70 °C** | Optional, only when genuinely measured surplus solar qualifies and it is economical |
| **OFF** | Peak periods (unless verified solar-only heating), holiday, protective withdrawal |

The heater's **native thermostat** runs the element and its ~8 °C hysteresis
(it reheats about 8 °C below the selected target). The controller selects a
thermostat target; it never drives the element directly and never claims that
a target proves a whole-tank temperature.

**Overnight:** Manual 45 °C. The bottom probe may fall below 42 °C while 45 is
selected; the owner accepts this. The controller does not chase a bottom-probe
temperature, does not start extra morning heating and raises no morning
deadline alarm.

### 1.3 Weekdays (owner's Aurora Tariff 93, fixed AEST tariff clock)

| Period (AEST tariff time; +1 h on the Hobart clock during daylight saving) | Thermostat |
|---|---|
| 21:00 – 07:00 | Manual 45 (or 70 if solar genuinely qualifies, which does not happen at night) |
| 07:00 – 10:00 peak | OFF, or verified solar-only heating if that peak policy is selected |
| 10:00 – 16:00 | Manual 62 started at the cheapest window that still finishes 30 min before the evening peak; Manual 70 when solar qualifies |
| 16:00 – 21:00 peak | OFF, or verified solar-only heating |

On a tariff without an afternoon peak, 62 is ready by the storage-ready time
(16:00 household time) and the target returns to 45 at the baseline time
(21:00).

### 1.4 Weekends

45 until the first fresh measured PV report of at least 0.5 kW opens the comfort
window (or, if PV never reaches it, the deadline fallback opens it in time).
In the window: Manual 62 planned to be ready by 15:30, grid assistance at
off-peak price allowed, never paused once selected; Manual 70 if solar
qualifies. At 18:00 the target returns to 45 (stored water is not cooled).
Confirmed 19 November 2026.

### 1.5 Peaks

The selected peak policy applies: *Never schedule heating during peak*, or
*Verified solar-only heating* (the owner's current choice). Solar-only peak
heating needs a commissioned circuit meter or the CT-free commissioning record,
fresh verified grid measurements and every command safeguard; it ends with a
protective OFF on sustained import, meter loss, uneconomic price or a hot tank.

### 1.6 Solar boost to 70 °C

Starts only when every one of these holds: optional boost enabled; commissioned
circuit meter or CT-free record; fresh grid meter; fresh temperature; probe at or
below 62 °C (or measured element power); **10 minutes of sustained export of at
least element power + 0.3 kW (3.3 kW for the 3 kW element)**; it can finish
before the next peak; it saves at least the configured minimum; command budget,
cooldown and protective-exit checks pass. It continues until 10 minutes of
continuous import above 0.2 kW or loss of valid measurement, then withdraws
(weekday → 62, otherwise → 45, peak → OFF) and waits the cooldown before another
start. Solar *production* alone never qualifies a boost; only genuine measured
grid export does.

### 1.7 Required storage without solar

Required 62 storage is never left to the weather: the latest start is calculated
from nominal element power (or slower measured power) and enforced on weekdays
and by the weekend deadline fallback.

### 1.8 Owner control

An app change seen by the controller pauses automation until **Resume**.
Hold, Holiday (OFF for the dates, at most 60 days) and the 12-hour Override
(Manual 62) take precedence over the policy. Manual owner control of the heater
through the Thermann app is never blocked.

### 1.9 Notifications

| Notification | When |
|---|---|
| Hot water may be running low | Fresh bottom probe below **35 °C** (configurable) within the observation lead before the **evening peak only** (decision 20 Nov 2026). Never before the morning peak. Notification only: it never grants heating permission or changes native protections |
| Fault, unconfirmed command, protective OFF unconfirmed, parked OFF cannot restore, Manual target not heating, status stale, cloud problem, forecast unavailable | As described in §2.9 |

### 1.10 Cloud polling

**Smart polling is the single normal mode**, configured in one place (the
Thermann Hot Water app). The controller follows the app automatically. A fixed
30-minute read schedule is the automatic fallback at startup, after
communication problems, for a missing or rejected plan, or after a scheduler
failure. The fallback never bypasses command freshness checks or cloud request
protections. The app keeps a *Fixed* choice for recovery only.

### 1.11 Forecasts are optional

EMHASS forecasts are an optional optimisation input. They may choose **when**
required 62 °C heating starts and refine the economics of a solar boost. They
never authorise a 70 °C boost: only fresh measured grid export (§1.6) can
qualify surplus, and without a forecast a boost is judged on the measured
surplus alone. If forecasts are missing, stale, flat or invalid, the fixed
temperature and tariff rules continue: weekday 62 °C is guaranteed by its
latest start, the weekend window by its deadline fallback, and overnight 45 °C
and peak OFF are unaffected. Losing live solar/grid measurements suspends solar
permission; surplus is never invented. The only household-load assumption
without a usable forecast is a conservative 1 kW floor (or the current
household load, if higher); there is no second load model.

### 1.12 Safety mechanisms that must be preserved

Exact-prior guarded transitions between OFF/45/62/70 only; fresh (≤ 60 s)
status before every command; confirmation by later status, never a repeated
POST; one command in flight; command spacing (15 min, except protective OFF);
optional-start and essential command budgets (OFF never budget-blocked); daily
cloud request budget; authentication guard and lock that is never reset
automatically; commissioning gates; restart reconciliation; native heater
protections untouched.

---

## 2. Implementation (Controller 0.18.1, app 1.5.0)

Paths are relative to the repository root.

### 2.1 Policy engine

`custom_components/thermann_shadow/simple_policy.py`

| Behaviour | Function |
|---|---|
| Precedence: owner override → holiday → 12-h Override → policy → command-slot reservation before peak | `SimplePolicy.decide` |
| Peak lockout and solar-only peak rules | `_policy`, peak branch |
| Weekday required 62 (deadline planning, cheapest window, latest start) | `_policy`, deadline branch |
| Overnight / opportunity (45, or qualified 70) | `_policy`, final branch |
| Weekend comfort window | `_weekend`, `pv_window_open` |
| Boost qualification and economics | `_boost`, `surplus_qualified`, `importing_continuously` |
| Native hysteresis planning constant (8 °C) | `PolicySettings.hysteresis_c` |
| Solar start headroom constant (0.3 kW) | `solar.SOLAR_START_HEADROOM_KW` |

No function selects 62 or 70 before the morning peak except a qualified solar
boost; `tests/test_operating_policy_0_18_0.py` guards this.

### 2.2 Command supervision

`controller.py`: commissioning (`missing_commissioning`), gates (`gates`),
confirmation (`_confirm`), owner override/hold/holiday/Override, restart
reconciliation (`restored`), alerts (`_supervise_alerts`). `executor.py` builds
observations, persists before publishing and publishes at most one message.

### 2.3 Tariff and clock

`model.py` `tariff_at`/`tariff_zone`; `config.parse_options` builds the Aurora
93 table from the four peak times. `tariff_clock = standard` is fixed AEST
(UTC+10) and is converted to the Hobart clock automatically; household times use
`time_zone`.

### 2.4 Forecasts

`forecast.py` `build_forecast`: only the EMHASS published `forecasts` series
for PV and household load (other shapes are not forecasts). PV is clipped to
the inverter limit and corrected by measured PV for 3 h; the uncertainty margin
and household allowance are applied; an unusable load series uses the floor
`FALLBACK_LOAD_KW` (1 kW) or the current house load. Missing or stale forecasts
assume no future solar for planning: weekday heating starts by the latest
start, the weekend window starts 62 at once, and an alert follows after 60
minutes. `simple_policy._boost` prices a boost on the qualified measured
surplus when no forecast is available. Evidence:
`tests/test_forecast_independence_week.py`, `tests/test_final_release_0_18_1.py`
and [evidence/SCENARIO_COVERAGE.md](evidence/SCENARIO_COVERAGE.md).

### 2.5 Measurements

`runtime.py` (grid sign, freshness, CT-free record match), `solar.py`
(`ct_free_record`, `grid_sanity`). PV production opens only the weekend window.

### 2.6 Polling

App: `thermowatt-heater/thermowatt_polling.py` (`AdaptiveSchedule`, v3 plans,
180 s lease, fixed fallback) and the `cloud_polling` option (`smart` | `fixed`).
Controller: `executor.py` sends v3 Smart plans (`adaptive.smart_plan`) only when
the app reports `polling_preference = smart` and advertises plan version 3.
Otherwise it sends nothing and the app stays on its fixed schedule.

### 2.7 Freshness limits

Command gate: status no older than the poll interval + 5 min. App: status ≤ 60 s
before a POST, one pre-command refresh otherwise. Planner probe freshness 75 min.
`status_max_age_minutes` (pre-peak warning) and `grid_max_age_seconds` (meter).

### 2.8 Budgets and confirmation

Optional starts limited by *Maximum commands per day*; essential commands may go
6 further; OFF never blocked. *Cloud request budget per day* with a 10-request
exit reserve for optional starts. App confirms with reads at 60 s and 300 s.

### 2.9 Alerts

`controller._supervise_alerts`: `pre_peak_low_hot_water` (evening peak only),
`protective_exit_unresolved`, `parked_off_cannot_restore`,
`peak_lockout_unverified`, `heater_meter_unavailable`, `storage_not_heating`,
`status_stale`, `cloud_fault`, `forecast_unavailable`, Override not applied,
faults and owner-override notices.

### 2.10 Settings

Every remaining setting has a documented effect: see [SETTINGS.md](SETTINGS.md)
(generated from the catalogue by `tools/build_owner_settings.py`). Settings
retired in 0.18.0 are moved by the entry migration into a preserved
`retired_options` record that nothing reads; see
[audits/2026-11-20/](audits/2026-11-20/README.md) for the inventory.

---

## 3. Rules for changing this system

1. A requirement exists only if it is written in §1 with a date, or in a
   decision record under `docs/decisions/`. A setting, default, test, fixture or
   historical document is never evidence of a requirement.
2. Changes to heating behaviour, commands, authentication, safety limits or
   polling authority need explicit owner approval (see `AGENTS.md`).
3. When a requirement is retired, remove its code, settings, validation and
   tests in the same change, migrate stored values into `retired_options`, and
   add it to §1.1.
4. Update §2 in the same pull request as any behaviour change.
