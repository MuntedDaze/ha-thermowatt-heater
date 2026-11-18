# Review of two proposed owner settings changes (19 November 2026)

No live setting was read or changed. Evidence: the controller code, the
recorded 11 November configuration snapshot in `docs/history/audit/`, and
synthetic replays (`tools/morning_solar_delay_replay.py`). Live checks the
owner still needs to make are listed as such.

## 1. Maximum commands per rolling 24 hours: 6 → 8

What the cap does: optional solar starts (70 °C boosts) stop once this many
commands, **including essential ones**, were sent in the last 24 h. Essential
commands may go 6 beyond it; OFF is never held back. Allowed range 4–10.

A normal weekday already uses about 4: OFF before each peak, a post-peak
start, and 45 at 22:00. A boost plus one withdrawal makes 6.

| Replay (Thursday, clear) | 0.16.1, cap 6 | 0.16.1, cap 8 | 0.16.2, cap 6 | 0.16.2, cap 8 |
|---|---|---|---|---|
| After a clear Wednesday | 70 at 11:00 | 70 at 11:00 | 70 at 11:00 | 70 at 11:00 |
| After a patchy Wednesday (boost/withdraw churn) | 62 at 11:00, **70 at 13:41** | 70 at 11:00 | 70 at 11:00 | 70 at 11:00 |

The only case where 8 helps is the recurring-boundary count error that 0.16.2
fixes. Raising the cap also allows two more cloud POSTs a day on bad days.

**Recommendation: keep 6 and install 0.16.2.** If 0.16.2 cannot be installed
soon, 8 is a reasonable interim (the essential ceiling becomes 14). In either
case it is better to reduce unnecessary transitions than to raise the cap:

- the in-session GoodWe gap withdrawal (each blip costs 2 commands; proposal
  P3 in `INVESTIGATION.md`);
- boost/withdraw churn on patchy days (the 10-minute cooldown and spacing
  already bound it);
- weekends: 0.17.0 never pauses a selected 62 target (≤ 3 commands a day in
  replay).

## 2. Household forecast input: flat GoodWe average → `sensor.hot_water_load_forecast_input`

What the controller does with it: net surplus = PV × (1 − 25 %) − load ×
(1 + 25 %) − 0.3 kW for every slot beyond the first 30 minutes (measured
export covers those). It decides whether a 70 °C boost is worth it and when
required heating starts. It never authorises a start; measured export does.

What the mapped sensor would publish (from the recorded configuration):

- a template copy of EMHASS `sensor.p_load_forecast`, unit W, with a
  `forecasts` list and `forecast_generated_at` from
  `input_datetime.emhass_forecast_generated`, refreshed every 30 minutes by the
  EMHASS automation (only on a successful optimisation);
- EMHASS `load_forecast_method: naive` from
  `sensor.goodwe_inverter_house_consumption`, with
  `number_of_deferrable_loads: 0`. **That consumption includes the water
  heater (no heater CT), so the forecast is yesterday's load including
  yesterday's heating cycle.**

Code checks the series must pass (`forecast.py`): available and not restored;
`forecast_generated_at` offset-aware, after the HA start and ≤ 120 min old;
unit W/kW; 2–577 strictly increasing points within 48 h; values 0–30 kW; no
value below 0.1 kW. Otherwise it silently uses a conservative flat floor
(1.0 kW or current house load), reported as `forecast_load_quality`.

| Replay, Thursday after a clear Wednesday | 70 starts |
|---|---|
| Household 0.5 kW flat | 11:00 |
| **Yesterday's whole-house load (what the mapping supplies)** | **12:08** (68 min `boost_value_below_switching_margin`) |
| Flat 1.2 kW (an average inflated by heater use) | 62 at 11:00, 70 at 13:06 |

The 3 kW heater cycle at 11:00–14:00 yesterday is forecast as household load
today, so the boost looks uneconomic at exactly the time it ran yesterday. On
a CT-free site this repeats every day. A flat average of whole-house
consumption has the same contamination, spread across the day.

**Recommendation: do not switch the mapping yet.** First confirm, read-only:

1. Settings → Devices & services → Thermann Controller → ⋮ → Download
   diagnostics: note `forecast_load_quality`, the load basis and the
   current flat value.
2. Developer tools → States → `sensor.hot_water_load_forecast_input`: check
   the state is numeric, `forecasts` has about 48 half-hour rows, and
   `forecast_generated_at` is within the last 30–60 minutes.
3. Compare its rows for 10:00–15:00 with yesterday's heater activity. If they
   rise by about 3 kW where the heater ran, the series includes the heater.

The mapping becomes worthwhile when the household series excludes the
heater: for example an EMHASS load sensor that subtracts heater power (needs
a heater CT), or the heater configured as an EMHASS deferrable load with a
matching load sensor. Until then the flat value should be the household
baseline without heating. A median of house consumption over hours when the
heater is idle is closer than a 24-hour mean.

## Owner-supervised procedure for either change (later, at the owner's choice)

Both settings are locked while Automatic heater control is on.

1. Choose a quiet time outside peak with no heating expected for 30 minutes.
2. Download diagnostics first (rollback record of current values).
3. Turn **Automatic heater control** off. The heater stays in its current mode.
4. Change one setting only:
   - Advanced/System → Commissioning and safeguards → **Maximum commands per
     day**; or
   - Solar & Meters → Solar and meter readings → **Forecast household
     electricity use** (entity mapping).
5. Save, then turn Automatic back on. The controller re-inspects the heater
   before sending anything.
6. Over the next day check the event log and `forecast_load_quality` /
   `commands_24h` in the report.
7. Rollback: repeat with the value recorded in step 2.
