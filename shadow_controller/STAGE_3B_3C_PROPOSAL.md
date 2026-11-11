# Stage 3b / 3c proposal — forecasts, whole-home solar advisor, tablet dashboard

**Design only. Nothing here is deployed or enabled.** Each item needs separate
owner approval. Home Assistant uses GoodWe, Thermann and Tapo **read-only**: Tapo
keeps all its own routines (humidity-controlled fans, relay schedules); no Tapo
switch, appliance, heater or notification automation is created in Stage 3a.

## 1. What exists today vs what needs data or hardware

| Capability | Existing entities | Needs |
|---|---|---|
| Live PV (AC), house, grid, tariff | GoodWe `total_power`, `house_consumption`, `meter_active_power`; planner tariff sensors | — |
| Today's PV kWh, import/export kWh | `today_s_pv_generation`, `meter_total_energy_import/export` | HA Energy dashboard configuration (owner) |
| Hot-water state, readiness, decision | Shadow Planner 0.4.0 | — |
| Heater energy (measured) | none; estimated from `WaterHeaterSts` + 3 kW steps | **CT/DIN energy monitor on the heater circuit (licensed electrician)** for verified kWh |
| Appliance power/energy | Tapo `*_current_consumption` (W), `*_today_s_consumption` / `*_this_month_s_consumption` (kWh), `switch.*` | — |
| Appliance cycle profiles | Tapo power histories | **weeks of history**: no washer/dishwasher/dryer cycle occurred in the 2.5 days available |
| Fridge | none found | a Tapo plug or CT if wanted |
| Forecast accuracy statistics | `sensor.p_pv_forecast` recorded each run | ≥14 days of clean (post-14:25 10 Nov) history |
| Weather for solar | Open-Meteo inside EMHASS; Forecast.Solar sensors | optional HA weather integration for display only |

Tapo inventory (read-only, from the recorder):
- **Washing machine**, **dishwasher**, **dryer** (the dryer plug reported only 9
  states; it may be offline or rarely used).
- **Main and ensuite towel rails**: ~76 W for 3–6 h cycles (~0.3 kWh), run by Tapo schedules.
- **Main and ensuite fans**: humidity-controlled by Tapo; leave as is.
- **Server** and **"jrig"**: ~174 W and ~176 W continuous (≈8.4 kWh/day together,
  ≈ $1.4–1.9/day at the Tariff 93 rates).
- **Network cupboard** and **garage**.

## 2. Accounting model (no double counting)

```
house_total (GoodWe)  =  heater (estimated or CT)  +  Σ tapo_devices  +  unmonitored_remainder
grid_net              =  pv_ac − house_total
```
GoodWe stays the household total. Tapo provides a breakdown *inside* it. The
remainder is derived and must never be negative beyond measurement noise; flag
it otherwise (e.g. a plug and the meter disagreeing in timing). The heater term is
labelled *estimated* until a CT exists. Template sensors:

- `sensor.house_load_excluding_hot_water` = house − 3 kW × [element on] (estimated).
- `sensor.monitored_appliances_power` = Σ Tapo W.
- `sensor.unmonitored_load` = house − heater − monitored appliances.

## 3. Forecast calibration and load de-embedding (proposal for later deployment)

1. **De-embedded load history.** Create
   `sensor.house_load_excluding_hot_water` (template; estimated, from the 0.4.0
   heater state). Exclude history before **10 Nov 2026 14:25** (meter
   commissioning).
2. **Offline comparison first.** On ≥14 days of clean history, compare these
   base-load forecasts by MAE and P90 error per 30-min slot:
   - (a) naive persistence of raw house load (today's EMHASS);
   - (b) naive persistence of the de-embedded load;
   - (c) median profile per slot × weekday/weekend over 14 days;
   - (d) EMHASS `mlforecaster` on the de-embedded sensor.

   Split by time (train on earlier days, test on later days) so nothing is fitted
   to the test days. Adopt a method only if it beats (b) on the held-out days.
3. **EMHASS change (separate approval):** point `sensor_power_load_no_var_loads`
   and `var_model` at the de-embedded sensor. That is EMHASS's own definition
   ("load without deferrable loads"). No fork.
4. **PV:** keep EMHASS as provider. Track bias per hour-of-day and cloud class
   over ≥14 days, with clipped periods (AC ≥ 4.85 kW) excluded from downward
   bias. Compare Forecast.Solar (tilt corrected to 22.5°) as an independent check.
   Evaluate EMHASS `set_use_adjusted_pv` only with clipped samples excluded.
   Widen uncertainty, never optimism, when the providers disagree.
5. **Acceptance:** held-out MAE improvement ≥15 % for load, documented PV bias
   bands, and no change to the comfort fallback.

## 4. Solar surplus advisor (read-only, advisory)

**Inputs:** PV AC, base load (de-embedded), grid, tariff + next change, forecast
PV/base for 15/30/60/120 min with P10/P50/P90, hot-water state and reserved
heating plan, Tapo appliance states and learned profiles.

**Shared energy budget (one ledger):**
```
available(t) = pv_ac(t) − base(t) − hot_water_plan(t) − running_appliances(t)
```
- The hot-water plan reserves its slots **first** whenever it carries a comfort
  requirement; optional hot-water heating competes on cost like any appliance.
- Each suggestion **reserves** its profile's expected power over its expected
  duration. A second appliance only sees what is left, so the same 1 kW is never
  promised twice. Suggestions are ranked by expected saving per start, then by
  confidence and convenience.

**Appliance profiles (learned from Tapo power history):**
- Cycle detection: start when power exceeds the idle threshold (e.g. 5 W above the
  standby median) for ≥2 min; end after a configurable idle gap (washer 10 min,
  dishwasher 20 min, dryer 5 min). Cycles shorter than a minimum energy are
  discarded as standby blips.
- Per appliance:
  - energy per cycle (median, P10/P90);
  - duration (median, P90);
  - mean power;
  - P50/P95/max power;
  - the high-power stage profile (time from start and duration of any stage
    above e.g. 1 kW);
  - daily, weekly and monthly kWh and cost.
- Programmes: cluster cycles by (energy, duration, peak timing). Report
  "programme uncertain" when clusters overlap or fewer than 5 cycles exist;
  never invent precision.
- Statistics are kept by HA long-term statistics on the Tapo energy sensors plus
  a small persisted summary per appliance (not a new database).

**Cost of running now vs later** uses the **whole energy profile**, never peak
watts. For a profile p(τ) over the cycle and surplus s(t):
```
cost(start) = Σ_τ Δτ · [ r(t) · max(0, p(τ) − s(t)) + f · min(p(τ), s(t)) ]
```
A 300 W programme with a 5 % stage at 2 kW can be the cheapest choice even if it
briefly imports. Alternatives compared: now, the best start in the forecast window,
and the next off-peak start. Report the saving and confidence (profile
reliability × forecast confidence).

**Example messages:**
- "1.2 kW exported for 15 min. Hot water is ready. Dishwasher (typ. 1.1 kWh,
  2 h 10 min) now would cost about $0.11 vs $0.19 tonight."
- "Surplus forecast to rise from 1.0 to 2.5 kW at 11:30. Waiting 40 min would
  cut the dryer's imports by about $0.25."
- "Peak until 22:00. The 3 kW heater now would import ~2 kW ($0.72/h); waiting is
  cheaper and comfort is protected."

## 5. Notifications (design; not enabled)

| Trigger | Condition (configurable) | Anti-spam |
|---|---|---|
| Sustained surplus | ≥ X kW (default 1.0) for ≥15 min and P50 forecast ≥ X for 30 min | 2 h cooldown; suppressed if hot water needs it |
| Appliance economical now | saving ≥ $0.10 and confidence ≥ medium; per-appliance opt-in | 1 per appliance per day |
| Better window later | saving ≥ $0.15 within 3 h | once per window |
| Hot-water risk | readiness `at_risk`/`shortfall`, or fallback due while native Schedule window closed | immediate; repeat at 30 min only if unresolved |
| Data unavailable | heater status or forecast unavailable > 45 min | once per outage + recovery note |
| Import spike / peak approaching | import > Y kW for 10 min in peak, or 15 min before a peak with heating planned | 1 per peak period |

Quiet hours (default 21:30–07:00, comfort alerts exempt), per-appliance
preferences and cooldowns are stored as HA helpers. Delivery uses the HA mobile
app notify service (local push via HA Cloud or the companion app). It is opt-in
and approved separately.

## 6. Whole-home wall-tablet dashboard (design)

Native cards, **sections** layout (4 columns on the tablet, 1 on a phone),
kiosk-friendly; large values readable at ~2 m. Each tile is badged *measured*,
*estimated* or *forecast*.

**View 1 — Home (tablet main):**

| Section | Content |
|---|---|
| Now | big tiles: solar AC kW (measured), house kW, grid import/export kW, self-consumption %, current tariff and rate, next change countdown |
| Today | PV kWh, export kWh / revenue, import kWh / cost, net cost (Energy dashboard statistics) |
| Hot water | tank reading gauge; heater ON/OFF/UNKNOWN with confidence; ownership "Native Schedule"; 42 °C morning and 70 °C afternoon readiness chips with deadlines; recommendation (colour) with saving; expected cost and solar share |
| Solar outlook | next 6 h forecast vs actual (history-graph with forecast attribute series), expected export/import, tomorrow's kWh, confidence/freshness |
| Suggestions | the advisor's top ranked appliance suggestion(s), each with saving and confidence; "no suggestion" when nothing is worthwhile |

**View 2 — Appliances:** per Tapo device tile (power now, running yes/no
inferred from the profile threshold, today's kWh and cost); per-appliance cycle
card (median kWh, duration, last cycle, programme count, profile confidence);
cost now vs later for major appliances.

**View 3 — History & reports:** statistics-graph cards for daily, weekly and
monthly PV, import, export, cost and revenue (long-term statistics); hot-water
energy and cost (estimated until a CT exists); forecast accuracy (MAE by day);
estimated scheduling savings, clearly separated from measured bills.

**View 4 — Settings and View 5 — Diagnostics:** as in 0.4.0.

Entities needed beyond today:
- `sensor.house_load_excluding_hot_water`, `sensor.monitored_appliances_power`,
  `sensor.unmonitored_load`;
- `sensor.self_consumption_ratio`, `sensor.import_cost_today`,
  `sensor.export_revenue_today` (utility_meter + template sensors);
- appliance profile summary sensors;
- solar advisor suggestion sensors.

## 7. Recorder and maintenance

- Exclude the large forecast attributes (`sensor.p_*_forecast`) from the recorder
  and keep their states. Keep `recorder` `purge_keep_days` at 10–14 days.
  Long-term statistics hold history beyond that at 5-min/hourly resolution.
- Shadow Planner controller attributes are large (~5.6 KB per change). Proposal:
  exclude `sensor.thermann_shadow_controller` attributes from the recorder and
  rely on the small numeric sensors for history.
- Tapo: keep energy sensors with `state_class` for statistics; exclude
  `*_auto_update_enabled`, `*_led` and similar config switches from the recorder.

## 8. Stage 3c — Native Schedule advisor backtest

0.4.0 already reports, read-only, today's predicted cost and readiness for the
current reference windows and three alternatives ("Schedule advisor today").
Before proposing any real Schedule change:

1. Collect ≥21 days of clean history (heater state, readings, PV, base load).
2. Replay each candidate window set day by day with the real readings and draws.
   Native behaviour is modelled as heating in windows until the thermostat is
   satisfied, calibrated on observed switch-offs.
3. Accept a candidate only if it meets 42 °C before the morning peak and
   65–70 °C before the evening peak on **every** replayed day (or no worse than
   the current windows), and lowers total cost. Report the cost distribution, not
   only the mean.
4. The owner changes the Schedule in the Thermann app; record the old windows for
   rollback. Verify the device clock after each DST change.

## 9. Order of work

1. 0.4.0 deployment and two weeks of observation (separate approval).
2. De-embedded load sensor + offline forecast comparison (3b-1).
3. Recorder trims (3b-2).
4. Energy dashboard + tablet view 1 (3b-3).
5. Tapo profile learning (read-only), appliance view, advisor suggestions (3b-4).
6. Optional notifications (3b-5, opt-in).
7. Schedule advisor backtest (3c).
8. Only then consider supervised control qualification (Stage 4).
