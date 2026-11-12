# Forecast setup — Shadow Planner 0.3.0

Forecasts are **optional and off by default**. Without them the planner still
works: it uses the measured HK1000 net export for the next 15 minutes only and
always reserves a full off-peak fallback. Forecasts improve *timing* (start on
partial solar early, or wait for better sun); they never delay the fallback.

Everything below is configured by the owner in Home Assistant. The planner only
**reads** the resulting entity states on its one-minute local timer. It never
calls EMHASS, Forecast.Solar, a weather service or Thermann, and forecast updates
cause **zero** Thermann requests. Nothing here touches the Thermowatt add-on.

## What the planner needs

Two optional entities, mapped in **Settings → Devices & services → Thermann
Shadow Planner → Configure** (first page):

| Mapping | Accepted shapes | Required attributes |
|---|---|---|
| **Optional published PV forecast** | EMHASS-style `forecasts` list *or* Forecast.Solar-style `watts` mapping | `unit_of_measurement` `W`/`kW`, `forecast_generated_at` |
| **Optional household load forecast or measured baseline** | EMHASS-style `forecasts` list *or* a plain numeric sensor (flat baseline) | list: `unit_of_measurement`, `forecast_generated_at`; numeric: `unit_of_measurement` only |

Then turn on **Use published forecasts** on the Settings dashboard.

`forecast_generated_at` must be an offset-aware ISO timestamp of when the forecast
was actually **calculated** — not when it was last republished. After an HA
restart the planner waits for a generation newer than its own start. A forecast
older than **Maximum forecast generation age** (default 120 min, max 360) is
ignored and the decision falls back conservatively.

How the planner uses them (all visible on the Diagnostics view):

- Net surplus = PV × measured correction × (1 − uncertainty) − load × (1 +
  uncertainty) − extra household allowance. Defaults: 25 % and 0.3 kW. Solar
  headroom (0.3 kW) applies to the *measured* surplus only.
- The measured-vs-forecast correction compares a 15-minute mean of the GoodWe PV
  reading with the forecast for now. It can only *reduce* PV, and it fades out
  linearly over 3 hours, so a cloudy reading now does not erase this afternoon.
- Gaps (such as Forecast.Solar overnight) count as **zero** solar, never held.
- Bad units, stale/future/pre-restart generation, non-finite values, unsorted or
  oversized series discard the whole forecast safely (`forecast_*` warnings).

## Option A — EMHASS (recommended if already running)

EMHASS publishes `sensor.p_pv_forecast` and `sensor.p_load_forecast` with a
`forecasts` attribute (`[{date, p_pv_forecast}, …]`) when horizon publishing is
enabled (the default). Custom EMHASS entity IDs also work: the value key is the
entity's own name. EMHASS does **not** publish a generation timestamp, so stamp
it where the owner's existing automation runs the optimisation.

1. Create a helper: **Settings → Devices & services → Helpers → Date and/or
   time** named `EMHASS forecast generated` (date and time), or in YAML:

   ```yaml
   input_datetime:
     emhass_forecast_generated:
       name: EMHASS forecast generated
       has_date: true
       has_time: true
   ```

2. In the **existing** automation that calls EMHASS (day-ahead or MPC), stamp
   the time only after a successful optimisation call. Keep your own command
   names; only the two marked steps are new:

   ```yaml
   - action: rest_command.emhass_dayahead_optim     # your existing call
     response_variable: emhass_result               # NEW
   - if: "{{ emhass_result.status < 300 }}"         # NEW: only on success
     then:
       - action: input_datetime.set_datetime
         target:
           entity_id: input_datetime.emhass_forecast_generated
         data:
           timestamp: "{{ now().timestamp() }}"
   - action: rest_command.emhass_publish_data       # your existing publish
   ```

   Do **not** stamp on `publish-data` alone: republishing an old plan is not a
   new forecast. A once-daily day-ahead run will usually exceed the 120-minute
   freshness limit; MPC runs every 5–30 minutes are a better fit.

3. Add two template sensors (`configuration.yaml` or a template helper):

   ```yaml
   template:
     - sensor:
         - name: Hot water PV forecast input
           unique_id: hot_water_pv_forecast_input
           unit_of_measurement: W
           state: "{{ states('sensor.p_pv_forecast') }}"
           availability: >
             {{ state_attr('sensor.p_pv_forecast', 'forecasts') is not none
                and has_value('input_datetime.emhass_forecast_generated') }}
           attributes:
             forecasts: "{{ state_attr('sensor.p_pv_forecast', 'forecasts') }}"
             forecast_generated_at: >
               {{ as_datetime(state_attr('input_datetime.emhass_forecast_generated',
                  'timestamp')).isoformat() }}
         - name: Hot water load forecast input
           unique_id: hot_water_load_forecast_input
           unit_of_measurement: W
           state: "{{ states('sensor.p_load_forecast') }}"
           availability: >
             {{ state_attr('sensor.p_load_forecast', 'forecasts') is not none
                and has_value('input_datetime.emhass_forecast_generated') }}
           attributes:
             forecasts: "{{ state_attr('sensor.p_load_forecast', 'forecasts') }}"
             forecast_generated_at: >
               {{ as_datetime(state_attr('input_datetime.emhass_forecast_generated',
                  'timestamp')).isoformat() }}
   ```

   If EMHASS publishes kW, set `unit_of_measurement: kW`. Check the unit in
   **Developer tools → States** before mapping.

## Option B — Forecast.Solar PV with a measured load baseline

The core Forecast.Solar integration (free, no API key) needs the array's
location, declination (tilt), azimuth and kWp. Confirm the owner's values
(≈6.6 kWp, 5 kW inverter limit) and HA's azimuth convention in the
[integration docs](https://www.home-assistant.io/integrations/forecast_solar/).
Its sensors do not carry an hourly series, so buffer the cached data with the
[`forecast_solar.get_forecast`](https://www.home-assistant.io/actions/forecast_solar.get_forecast/)
action, which returns data HA already holds and does not request a new forecast.

1. Find the Forecast.Solar config-entry ID: **Developer tools → Actions →
   Forecast.Solar: Get forecast**, pick the entry, then switch to YAML mode.
2. Add a trigger-based template sensor:

   ```yaml
   template:
     - triggers:
         - trigger: time_pattern
           minutes: "/15"
         - trigger: homeassistant
           event: start
       actions:
         - action: forecast_solar.get_forecast
           data:
             config_entry: YOUR_FORECAST_SOLAR_ENTRY_ID
             resolution: hourly
             start: "{{ now().replace(minute=0, second=0, microsecond=0) }}"
             end: "{{ now() + timedelta(hours=36) }}"
           response_variable: solar
       sensor:
         - name: Hot water PV forecast input
           unique_id: hot_water_pv_forecast_input
           unit_of_measurement: W
           state: "{{ solar.watts.values() | list | first | default(0) }}"
           attributes:
             watts: "{{ solar.watts }}"
             # Last successful Forecast.Solar refresh in HA (hourly on the free
             # plan). Verify it advances in Developer tools before relying on it.
             forecast_generated_at: >
               {{ states.sensor.energy_production_today.last_reported.isoformat() }}
   ```

   Replace `sensor.energy_production_today` with your Forecast.Solar "Estimated
   energy production - today" entity. Its `last_reported` advances each time HA
   receives a new forecast; if Forecast.Solar fails, the entity becomes
   unavailable instead of advancing.

3. Household load: Forecast.Solar has no load forecast. Use EMHASS's load
   forecast (Option A, template 2) or a measured baseline from the built-in
   **Statistics** helper (**Helpers → Statistics**, source
   `sensor.goodwe_inverter_house_consumption`, characteristic *mean*, max age
   24 hours). Map that numeric sensor as the load. It is a flat allowance with
   no daily shape, shown as `household_load_is_flat_baseline_not_daily_profile`.
   GoodWe house consumption can include native heater runs, which makes the
   baseline higher and therefore more conservative.

## Keep the Recorder small

Forecast attributes can be large. Exclude the two input sensors from history:

```yaml
recorder:
  exclude:
    entities:
      - sensor.hot_water_pv_forecast_input
      - sensor.hot_water_load_forecast_input
```

## Verify before enabling

1. **Developer tools → States**: each input sensor has the expected unit, a
   `forecasts` list or `watts` mapping with future timestamps, and a
   `forecast_generated_at` within the last two hours.
2. Map them in Configure, then turn on **Use published forecasts**.
3. On the Diagnostics view, check: Source `published_pv_and_house_load`, a small
   age, a non-zero interval count, and a plausible PV error/correction on a
   sunny day. *Forecast net surplus* on Hot Water should look reasonable.
4. If Source shows `unavailable`, the warnings list names the reason
   (`forecast_stale_or_pre_restart`, `forecast_unit_invalid`, …). The planner is
   then behaving exactly as with forecasts off.

Compare forecast and measured PV for a few representative days before trusting
forecast-driven waiting. No real-data forecast accuracy has been measured for
this installation.

## Why forecasts matter

Without a qualified forecast, 0.4.0 credits only the measured AC solar for the
next 30 minutes and assumes **zero** solar after that. It will therefore heat now
on available solar when that is the cheapest option. It will never recommend
waiting for sun it cannot see. A qualified forecast lets it recognise genuinely
cheaper solar later. Waiting still needs a saving of at least 5 c per kWh that
would be heated now, and a viable comfort fallback.

The EMHASS household-load forecast currently includes past heater cycles (and,
before 10 Nov 14:25, PV output). 0.4.0 therefore defaults to the de-embedded
measured base load (`base_load_source: measured_only`). See
[STAGE_3B_3C_PROPOSAL.md](../docs/history/controller/STAGE_3B_3C_PROPOSAL.md) for the de-embedding plan.
