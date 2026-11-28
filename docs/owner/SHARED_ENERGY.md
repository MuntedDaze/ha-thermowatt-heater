# Thermann Controller 0.18.4 owner verification and migration

The starting installation is Controller 0.18.3 on Home Assistant Core
2026.11.3. Test the controller update with the current direct meter mappings
first. The Thermann Hot Water app remains on 1.5.1. The controller entry schema
remains 1.6. The upgrade retains the command topic, options, MQTT entities,
controller storage and fault state. Shared power can be configured later.

## Notification audit

| Path | Finding and expected result |
|---|---|
| Thermann Hot Water app | Publishes MQTT conditions and diagnostics. The repository app does not send phone notifications. Its authentication stop, retry/backoff, quota accounting, scheduled reads and command gates remain authoritative. |
| Controller status and health | 0.18.3 could apply a generic status-age limit when a recent local decision no longer matched the quiet condition, even during a bridge-accepted gap. It also paged immediately for non-OK states such as `starting`, `unknown` and first backoff. Quiet alerts now use the accepted deadline from fresh bridge diagnostics, tied to the same successful poll, plus five minutes. The original command and planner freshness limits still apply. |
| Startup, reload and network failure | Startup allows the current fixed interval plus five minutes for the bridge to come up. A missing or overdue status needs ten minutes of the combined incident; a backoff or quota cooldown needs two reported failures or 65 minutes. A fresh authorization lock requiring an operator can page promptly. A successful ordinary recovery dismisses the notice silently. One unresolved incident persists across reload/restart through controller storage. |
| Actual loss of hot water | The existing parked-OFF warning still applies when a required heat target cannot be restored for 30 minutes. This takes precedence over an accompanying cloud notification. The existing fresh low-water warning stays confined to before the evening peak. Override failure and verified sustained lack of heating can still notify. |
| Command and safety | Controller lockouts still notify, including an unresolved command that faults while automatic control is off. A protective exit blocked by cloud backoff or a lock can notify promptly. A normal OFF confirmation has six minutes to settle before a notice. A faulted or out-of-band controller action that needs the owner to act stays actionable. |
| Optional inputs | Forecast and circuit-meter loss remain visible in diagnostics. A circuit-meter failure during an active solar session can still give rise to a protective-exit warning. |
| Automatic control disabled | No ongoing controller monitoring/availability phone notices. A previously initiated protective obligation or latched command fault can still need attention. |
| External HA automations | The checked-in HA export contains the EMHASS publish automation and no phone action. The historical `OWNER_WATCHDOG.yaml.example` could page whenever the controller evaluation timestamp is absent, including during startup or intentional disable, if independently installed. No current live automation export or traces were supplied. |

### Verify notification routes in Home Assistant

1. In **Settings → Automations & scenes**, search for `Thermann`,
   `Thermowatt`, `hot water`, `heater` and `cloud`. Inspect YAML and
   traces, including scripts and blueprint instances. For YAML-managed
   configuration, search all included packages and automations for
   `notify.`, `notify.send_message` and `persistent_notification.create`
   as well as the mapped cloud/last-poll entities. A phone alert from a
   local automation has its own trace and its own action.
2. Where a duplicate phone-only watchdog alerts on raw status age, `unknown`
   cloud health or ordinary meter/forecast loss, disable that duplicate
   automation after saving its YAML. Leave any separate heater safety
   automation enabled. If using a controller-evaluation watchdog, have it
   check the local controller heartbeat and automatic-control state. Use a
   startup grace period and a persistent incident flag if the watchdog pages
   independently. The old example is historical.
3. The controller's **Notification service** field takes the existing service
   name without `notify.`. Blank gives actionable Home Assistant
   persistent notifications only. While automatic control is off, observe
   the next normal overnight interval and an ordinary HA reload.

To identify a previous phone notification's actual origin, collect its
timestamp, title and automation trace if available. Export redacted history
for the successful-poll timestamp plus its diagnostic attribute, cloud health,
consecutive failures, authorization guard mode, accepted Smart plan and next
deadline, controller state/last evaluated, and the accompanying HA startup or
reload time. The 25 November parked-OFF incident has recorded evidence and
an offline replay. The newer missing-status/unknown-health notices have no
matching live incident traces in the repository.

## Map the shared instantaneous readings

1. Create and download a full backup in **Settings → System → Backups**.
   Record the current Thermann Controller mappings and options and save the
   existing selector package. During a separately approved installation,
   leave automatic control off and check that no command is awaiting
   confirmation. Replace `/config/custom_components/thermann_shadow/` with
   the reviewed commit's `custom_components/thermann_shadow/` and restart
   Home Assistant. Keep the existing configuration entry and bridge app.
   Verify Controller 0.18.4 in the diagnostic report.
2. In **Developer tools → States**, inspect
   `sensor.home_energy_grid_power`, `sensor.home_energy_solar_power` and
   `sensor.home_energy_household_power`. All three must carry the following
   attributes beside their numeric W or kW state:

   | Attribute | Value supplied by the existing selector |
   |---|---|
   | `measurement_source` | The exact source label that supplied this value, matching `sensor.home_energy_source`. |
   | `measurement_observed_at` | ISO 8601 with UTC offset, from the original physical sample. If the producer has no acquisition time, use its actual raw HA entity report time once you confirm it reports physical measurements, including unchanged values. |

   If absent, add the attributes to each of the three **existing sensor
   definitions** in the installed selector YAML. Use the same per-source
   payload or raw state object that supplies that sensor's value. In
   `attributes:`, set `measurement_source` to the source captured with
   that value, and `measurement_observed_at` to the payload timestamp or
   the selected raw state's `last_reported.isoformat()`. Publish value,
   source and timestamp from the same selector decision. Keep the three
   existing unique IDs. If a selected source computes a value from several
   measured inputs, use the oldest contributing observation time, and mark
   it unavailable if a contributor is invalid. Set the attributes to
   unavailable together with an invalid value. The live selector YAML and
   underlying raw attribute names were unavailable for this audit, so check
   them before editing its templates. Preserve the selector's 60 s inverter
   freshness, 150 s HK1000 freshness and three distinct inverter reports on
   recovery.

   Re-evaluate a template without new hardware data and confirm the reported
   measurement timestamp stays fixed. A current YAML evaluation time,
   shared template `last_reported`, or `now() - data_age` is insufficient.
   `sensor.home_energy_data_age` can be used to cross-check the raw age.
3. In **Settings → Devices & services → Thermann Controller → Configure →
   Solar & Meters → Solar and meter readings**, set the following fields
   together. Leave the currently working EMHASS output, dedicated circuit
   meter and cumulative energy entity mappings as recorded.

   | Field | Entity |
   |---|---|
   | Shared energy selected source | `sensor.home_energy_source` |
   | Shared energy data valid | `binary_sensor.home_energy_data_valid` |
   | Net power bought from or sent to the grid | `sensor.home_energy_grid_power` |
   | Solar panel production | `sensor.home_energy_solar_power` |
   | Inverter's usable AC output | `sensor.home_energy_solar_power` |
   | Whole-house electricity use | `sensor.home_energy_household_power` |

   The grid mapping is signed net power. The separate shared import/export
   power sensors and grid voltage remain available for observation and are
   unused by Thermann. Keeping both selector fields blank supports the
   original direct meter mappings.
4. Verify **Positive means buying power** on both sources using existing
   household consumption and live telemetry, then record the verification
   in **Solar forecasts and grid meter**. Switching shared mappings clears
   the previous grid verification. If using a CT-free setup, avoid reusing
   the old record. Establish that PV + import − export agrees with whole
   household load in W/kW on both sources and repeat **Set up experimental
   CT-free solar** only in a separately approved commissioning session.
   Site power and the dedicated heater CT have separate commissioning.
5. With automatic control still off, observe actual distinct reports, fallback,
   recovery and both sources unavailable. Thermann applies its existing meter
   maximum age (default 120 s) to each original measurement even if the
   selector still declares HK1000 valid at 121–150 s. The solar history starts
   over on each source change. Optional heat uses the existing withdrawal
   logic if input continuity is lost. Weekday required storage, weekend
   deadline fallback and baseline operation have no elective solar-data
   prerequisite. Record any sign or age discrepancies before progressing.
6. To roll back the mappings, restore the recorded direct grid/solar/house
   entities and clear both selector fields in the same save. Restore meter
   verification only after checking the direct sign and any applicable
   CT-free commissioning. Leave the cumulative entities and their history in
   place. If rolling back the controller itself, reinstall the 0.18.3
   controller files after restoring the direct mappings, then restart HA.

## EMHASS and historical household load

The recorded EMHASS config used `sensor.goodwe_inverter_house_consumption`
as `sensor_power_load_no_var_loads`, retrieved two days on 30-minute
intervals, and allowed interpolation of missing household and PV history.
The actual live settings may now differ. The following audit and migration
order keeps existing histories and separates a verified measured load history
from the published forecast.

| Entity | Role and migration |
|---|---|
| `sensor.goodwe_valid_household_power` | Its definition and consumers are absent from the tracked repository. Check whether it is the active EMHASS input and whether its template outputs zero or retains the last state during an outage. Preserve its current ID and Recorder history. |
| `sensor.goodwe_inverter_household_average_power` | No current definition or forecast mapping in the repo. Inspect the source and units. A smoothed value loses the timing of household load and is unsuitable as a drop-in raw load input. |
| `sensor.goodwe_valid_household_average_24h` | No current definition or consumers in the repo. Inspect its history window and valid-sample coverage. Keep it for existing uses. |
| `sensor.hot_water_pv_forecast_input` and `sensor.hot_water_load_forecast_input` | Keep both entity and unique IDs, published `forecasts` series and generation timestamp. They carry forecast horizons into Thermann. Keep the output forecasts separate from load-history inputs. |

1. Export the live EMHASS configuration and the forecast automation. Search
   all YAML, scripts, EMHASS runtime overrides and dashboard references for
   those names. In **Settings → Devices & services → Entities**, confirm the
   provider of each helper. Compare existing plot history, units, availability
   and actual source for two representative days, including an outage.
2. After the selector exposes physical timestamps, create a **parallel**
   history sensor with a new ID, `sensor.home_energy_emhass_load`, by adding
   this YAML under `template:` in the owner's HA packages. It uses the
   stricter 120 s ceiling for EMHASS and also requires selector validity.
   Keep the older history sensor, and make sure Recorder includes the new
   helper for at least the configured lookback plus one day.

   ```yaml
   template:
     - sensor:
         - name: Home energy EMHASS load
           unique_id: home_energy_emhass_load
           unit_of_measurement: W
           device_class: power
           state_class: measurement
           availability: >-
             {% set e = 'sensor.home_energy_household_power' %}
             {% set v = states(e) | float(none) %}
             {% set s = states('sensor.home_energy_source') %}
             {% set t = as_datetime(state_attr(e, 'measurement_observed_at'), none) %}
             {{ is_state('binary_sensor.home_energy_data_valid', 'on')
                and s not in ['unknown', 'unavailable', '']
                and state_attr(e, 'measurement_source') == s
                and not state_attr(e, 'restored')
                and state_attr(e, 'unit_of_measurement') in ['W', 'kW']
                and v is not none
                and 0 <= (v * (1000 if state_attr(e, 'unit_of_measurement') == 'kW' else 1)) <= 30000
                and t is not none and t.tzinfo is not none
                and 0 <= as_timestamp(now()) - as_timestamp(t) <= 120 }}
           state: >-
             {% set e = 'sensor.home_energy_household_power' %}
             {% set v = states(e) | float(none) %}
             {{ v * (1000 if state_attr(e, 'unit_of_measurement') == 'kW' else 1)
                if v is not none else none }}
           attributes:
             measurement_observed_at: >-
               {{ state_attr('sensor.home_energy_household_power', 'measurement_observed_at') }}
             measurement_source: >-
               {{ state_attr('sensor.home_energy_household_power', 'measurement_source') }}
   ```

3. Keep EMHASS on its current inputs during collection. Review Recorder
   history with physical report times, including source changes and one
   missing-data interval. Verify that missing values appear as unavailable
   and that every completed interval for a test optimization has legitimate
   measurement coverage. A history chart drawing a line across an outage
   does not establish coverage.
4. After a complete representative lookback, test with the installed EMHASS
   version and a separate test configuration. Set
   `sensor_power_load_no_var_loads` to `sensor.home_energy_emhass_load`.
   Remove this input from `sensor_replace_zero` and `sensor_linear_interp`
   (or the installed version's equivalent), including any per-run override
   such as `var_replace_zero`. Leave PV inputs and existing optimization
   parameters intact. Inspect the **prepared load series** and test an
   outage inside the lookback. If the installed EMHASS silently holds,
   interpolates or fills these gaps, retain the existing production input
   and delay cutover until this behavior is addressed. A current valid
   reading alone cannot make a historical gap suitable. Keep Thermann's
   optional forecasts disabled if the current load input is known to be
   contaminated.
5. For an approved cutover, use the same tested setting in production.
   Insert this condition immediately before the EMHASS optimization action.

   ```yaml
   - condition: template
     value_template: >-
       {% set e = 'sensor.home_energy_emhass_load' %}
       {% set t = as_datetime(state_attr(e, 'measurement_observed_at'), none) %}
       {{ is_state('binary_sensor.home_energy_data_valid', 'on')
          and is_number(states(e))
          and state_attr(e, 'measurement_source') == states('sensor.home_energy_source')
          and t is not none and t.tzinfo is not none
          and 0 <= as_timestamp(now()) - as_timestamp(t) <= 120 }}
   ```

   Keep the existing success checks for optimization and publication and
   require two newly reported output horizons before advancing the generation
   timestamp. Verify both Thermann forecast entities have valid recent
   horizons. On a failed run, leave generation time unchanged and allow the
   normal forecast-age limits to apply. Roll back by restoring the saved
   EMHASS input and its preprocessing settings. Keep both old and new history
   entities and both forecast outputs.

References for the installed version review include [EMHASS configuration](https://emhass.readthedocs.io/en/stable/config.html)
and [Home Assistant template sensor availability](https://www.home-assistant.io/integrations/template/).

## Daily and lifetime energy audit

- The Home package owns `sensor.home_energy_status` and compares it against
  `ready` in five energy helpers. The Home dashboards also consume it.
  Confirm whether the selector defines a similarly named entity by checking
  the template provider, its YAML `unique_id`, the entity registry and any
  `sensor.home_energy_status_2`. Keep the current daily-status ID bound to
  the existing daily package. If the selector created a duplicate, plan a
  separate unique ID for that selector diagnostic and verify its consumers
  before any rename. Thermann maps `sensor.home_energy_source` and
  `binary_sensor.home_energy_data_valid` for the selector.
- The Home tiles read long-term statistics for the inverter lifetime grid
  counters, while `home_grid_import_meter` and `home_grid_export_meter`
  independently derive daily values from those same counters. The separate
  energy-monitoring package also derives `em_grid_import_daily` and
  `em_grid_export_daily`, plus cost/tariff series. These can coexist, but
  counting two derived entities as independent energy sources would double
  count. Check **Settings → Dashboards → Energy** for duplicate inputs and
  **Developer tools → Statistics** for each statistic ID, units, reset
  handling and metadata warnings.
- If the inverter is offline over midnight, a cumulative difference is
  recorded on recovery. Neither the utility meter reset nor a statistics
  change during the new day can allocate an unobserved difference to both
  days accurately. Compare at least two midnight windows and a daylight
  saving boundary. Export timestamped lifetime states, `last_reset` and
  `last_valid_state` of the daily meters and statistics buckets, plus a
  retailer interval export or a continuous independent meter if available.
  A true counter reset, a transient backwards reading and a different
  hardware counter's starting total have different meanings. Inspect the
  source of any decrease before interpreting a daily jump.
- Recommended separate migration: compare at least a week of overlap with a
  single continuously available cumulative source, including offline
  overnight and a local midnight. Account for differences between HA local
  calendar days and retailer billing intervals. If the continuous source is
  confirmed, create a new statistic ID and pick a documented midnight for
  forward-only reporting. Preserve old IDs and their historical ranges. The
  live selector's power fallback leaves cumulative meter mapping separate.

See [the daily package behavior](HOME_DASHBOARD.md#energy-how-the-figures-are-obtained-and-what-was-investigated) and
[Home Assistant's statistics model](https://data.home-assistant.io/docs/statistics/).

## Before-and-after replay

The same mocked bridge and tank scenarios ran on 0.18.3 and 0.18.4.
Requests include all mocked HTTP calls observed during each scenario, including
any startup/recovery calls. A notice represents a controller dispatch eligible
for a phone message when its notification service is configured.

| Scenario | API calls, before → after | Notices, before → after | Heating result on both |
|---|---:|---:|---|
| Smart overnight through morning peak | 9 → 9 | 3 → 0 | Manual 45 °C until the normal peak OFF |
| Temporary backoff while at Manual 45 °C | 5 → 5 | 2 → 0 | Manual 45 °C, no command |
| One-hour outage at peak end | 5 → 5 | 3 → 1 | One Manual 45 °C restore after recovery |
| Three-hour outage at peak end | 6 → 6 | 4 → 1 | One Manual 45 °C restore after recovery |

In both peak-end outages the remaining notice was the 30-minute parked-OFF
warning. The three-hour replay had one failed retry after the initial failure.
Run `python tools/reliability_replay.py` from the repository root. To compare
0.18.3, run the same script by absolute path with the working directory set to
an exported 0.18.3 checkout. The replays use synthetic credentials, mocked
HTTP and in-memory MQTT.
