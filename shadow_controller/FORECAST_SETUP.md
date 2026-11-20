# Forecast setup (optional)

Forecasts are **optional and off by default** ([operating policy §1.11](../docs/OPERATING_POLICY.md)).
They only optimise: they can choose *when* required 62 °C heating starts and
refine the economics of a solar boost. They never authorise a 70 °C boost
(only fresh measured grid export can), and without them the controller keeps
the fixed rules: weekday 62 °C by its latest start, the weekend window by its
deadline, overnight 45 °C and peak OFF. Forecast updates cause **zero**
Thermann requests; the controller only reads Home Assistant states.

## What the controller reads

Two optional entities, mapped in **Settings → Devices & services → Thermann
Controller → Configure → Solar & Meters → Solar and meter readings**:

| Mapping | Accepted shape | Required attributes |
|---|---|---|
| **Forecast solar production** | EMHASS `forecasts` list | `unit_of_measurement` `W`/`kW`, `forecast_generated_at` |
| **Forecast household electricity use** | EMHASS `forecasts` list | `unit_of_measurement` `W`/`kW`, `forecast_generated_at` |

Then turn on **Solar forecasts and grid meter → Use published forecasts**.

Only this EMHASS shape is a forecast (0.18.1). Anything else means no future
solar is assumed. Without a usable household-load forecast the controller
assumes a conservative 1 kW (or the current household load, if higher); there
is no other load model.

`forecast_generated_at` must be an offset-aware ISO timestamp of when the forecast
was actually **calculated**, not when it was last republished. After a Home
Assistant restart the controller waits for a generation newer than its own
start. A forecast older than **Maximum forecast generation age** (default
120 min) is ignored.

How forecasts are used (visible in the diagnostic report):

- Net surplus = PV × measured correction × (1 − uncertainty) − load × (1 +
  uncertainty) − extra household allowance (defaults 25 % and 0.3 kW).
- The measured-vs-forecast PV correction fades out over 3 hours.
- Gaps count as **zero** solar, never held.
- Bad units, stale/future/pre-restart generation, non-finite values, unsorted or
  oversized series discard the whole forecast safely (`forecast_*` warnings).

## EMHASS setup

EMHASS publishes `sensor.p_pv_forecast` and `sensor.p_load_forecast` with a
`forecasts` attribute (`[{date, p_pv_forecast}, …]`) when horizon publishing is
enabled (the default). Custom EMHASS entity IDs also work: the value key is the
entity's own name. EMHASS does **not** publish a generation timestamp, so stamp
it where the existing automation runs the optimisation.

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
   the time only after a successful optimisation call:

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
   new forecast. MPC runs every 5–30 minutes fit the 120-minute limit better
   than a once-daily day-ahead run.

3. Add two template sensors:

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

   If EMHASS publishes kW, set `unit_of_measurement: kW`.

## Keep the Recorder small

```yaml
recorder:
  exclude:
    entities:
      - sensor.hot_water_pv_forecast_input
      - sensor.hot_water_load_forecast_input
```

## Verify

1. **Developer tools → States**: each input sensor has the expected unit, a
   `forecasts` list with future timestamps, and a recent `forecast_generated_at`.
2. In the diagnostic report, the forecast source is `published_pv_and_house_load`
   with a small age and a non-zero interval count.
3. If the source shows `unavailable`, the warnings name the reason. The
   controller then behaves exactly as with forecasts off: required heating
   continues, and a solar boost is judged on the measured surplus alone.
