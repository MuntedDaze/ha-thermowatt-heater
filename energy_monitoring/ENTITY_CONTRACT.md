# Integration contract: energy monitoring ↔ Thermann Controller

Baseline: controller 0.9.1 at `1b29be1` (PR #27). This file is the interface between this package and the controller work. Neither side imports the other; they meet only through Home Assistant entities.

## Rules

- This package only reads controller and bridge entities. It never calls a controller service or writes an entity.
- The controller may read any `em_` entity below. IDs are stable: they come from fixed names and unique IDs, not from the meter model.
- An `em_` sensor is `unavailable` when its inputs are; it is never a guessed zero. Treat `unavailable` and `unknown` as "no measurement".
- Hot-water entities exist only once the hot-water CT is mapped. Until then they are absent, not zero.
- Files this branch owns: `energy_monitoring/**`, `tests/test_energy_monitoring_*.py`, `tests/energy_template_shim.py`, `.github/workflows/energy-monitoring.yml`. It changes nothing else.

## 1. Entities this package provides

Power is in W, energy in kWh, money in AUD.

### Always present

| Entity | Meaning | Statistics |
| --- | --- | --- |
| `sensor.em_grid_import_power`, `sensor.em_grid_export_power` | Signed meter split into two non-negative values | mean |
| `sensor.em_solar_power`, `sensor.em_house_power` | Clamped at zero | mean |
| `sensor.em_solar_self_consumed_power` | solar − export | mean |
| `sensor.em_solar_forecast_power` | EMHASS current-slot forecast, state only | mean |
| `sensor.em_tracked_power`, `sensor.em_untracked_power` | Sum of non-overlapping measured loads; house − tracked. Attribute `raw_residual_w` is the unclamped difference | mean |
| `sensor.em_tariff_period` | `peak` or `off_peak` | none |
| `sensor.em_import_price`, `sensor.em_feed_in_price` | AUD/kWh now; unavailable until rates are set | mean |
| `sensor.em_house_energy`, `sensor.em_solar_self_consumed_energy`, `sensor.em_untracked_energy` | Integrated from the powers above | sum |
| `sensor.em_grid_import_peak_energy`, `sensor.em_grid_import_off_peak_energy` | Import meter steps by tariff period | sum |
| `sensor.em_grid_import_cost`, `sensor.em_grid_export_earnings`, `sensor.em_solar_self_consumption_savings` | Running totals priced at the moment of each step. Attribute `unpriced_kwh` | sum |
| `sensor.em_monitoring_health` | `ok`, `degraded` or `critical`. Attributes `missing`, `stale`, `rates_set`, `tariff_matches_controller` | none |
| `sensor.em_monitoring_quality` | Percentage of monitored sources available and fresh | mean |

### Per mapped CT circuit (`<key>` = `hot_water`, `air_conditioner`, `oven`)

| Entity | Meaning |
| --- | --- |
| `sensor.em_<key>_power` | Absolute circuit power |
| `sensor.em_<key>_energy` | The meter's kWh total, or the integral of power when it has none |

### Hot water, once its CT is mapped

| Entity | Meaning |
| --- | --- |
| `binary_sensor.em_hot_water_element_on` | Power above `element_on_watts` (default 1000 W), on after 30 s, off after 60 s. **A measurement**, unlike the controller's meter-inferred `heater_element_state` |
| `sensor.em_hot_water_grid_power`, `sensor.em_hot_water_solar_power` | Marginal attribution: grid = min(element, grid import) |
| `sensor.em_hot_water_grid_energy`, `sensor.em_hot_water_solar_energy` | Integrals of the two above |
| `sensor.em_hot_water_grid_cost` | Imported cost of heating |
| `sensor.em_hot_water_solar_opportunity_cost` | Feed-in income forgone; never part of the bill |
| `sensor.em_hot_water_element_runtime_today`, `sensor.em_hot_water_cycles_today` | Hours on and number of runs since local midnight |
| `sensor.em_hot_water_cycle_start` | Timestamp of the current or last run's start, with the meter snapshot as attributes |
| `sensor.em_hot_water_last_cycle` | One state per completed run (below) |

### Heating-cycle record

`sensor.em_hot_water_last_cycle` changes once per completed element run. State: energy in kWh. Attributes:

| Attribute | Meaning |
| --- | --- |
| `started`, `ended` | ISO timestamps (debounced by 30 s and 60 s) |
| `duration_minutes` | ended − started |
| `grid_kwh`, `solar_kwh` | Attribution over the run |
| `temperature_start_c`, `temperature_end_c`, `temperature_rise_c` | Bottom-sensor reading from the controller at each end |
| `status_age_start_s`, `status_age_end_s` | Age of that cloud reading at each end: use it to weight or discard the temperature |
| `tariff_period_at_end` | `peak` or `off_peak` |

Any figure whose inputs were unavailable is `None`. Thermostat micro-cycling produces several short records; a consumer should merge runs separated by less than its own threshold.

**Retention:** the Recorder keeps these states for its purge period (10 days by default); long-term statistics keep only the numeric totals. A learning module that needs more history should consume each record when the state changes and keep its own fitted parameters, or the owner can raise `recorder.purge_keep_days`.

## 2. Controller and bridge entities this package reads

All exist at baseline 0.9.1 and are mapped under `hot_water:` in `entity_map.yaml`.

| Use | Entity |
| --- | --- |
| Mode, target, tank reading | `sensor.thermann_shadow_thermann_mode`, `…_thermann_target`, `…_bottom_temperature` |
| Plan and reason | `…_automatic_control_state`, `…_automatic_control_reason`, `…_policy_wanted_state`, `…_policy_mode`, `…_decision_code`, `…_next_intended_action`, `…_next_heating_start`, `…_next_heating_stop`, `…_latest_continuous_heating_start`, `…_soft_target_time`, `…_heating_time_needed` |
| Operating mode, fault, inferred element | `…_hot_water_operating_mode`, `…_controller_fault`, `…_heater_element_state` |
| Tariff cross-check | `…_current_tariff` |
| Commands and requests | `…_last_command`, `…_last_command_result`, `…_commands_in_last_24_hours`, `…_cloud_requests_in_last_24_hours`, `…_observed_requests_per_hour` |
| Bridge | `sensor.home_cloud_health`, `sensor.home_status_age`, `sensor.home_last_successful_poll`, `sensor.home_last_cloud_error`, `sensor.home_cloud_request_attempts_local_lifetime` |

If the controller renames or retires any of these, only `entity_map.yaml` changes.

## 3. Requested from the controller (do not exist yet)

The names in the first column are **map keys**, not entity IDs. No entity ID is assumed: when the controller exposes one, put its real ID under `hot_water:` in the map and regenerate. Until then the dashboard shows a note in its place.

| Map key | Wanted | Shape |
| --- | --- | --- |
| `expected_completion` | When the current or next heating run is expected to reach its target | `device_class: timestamp`; `unknown` when not heating and nothing is planned |
| `next_poll` | When the bridge or controller will next poll the cloud | `device_class: timestamp` |
| `poll_interval` | The current adaptive poll interval | duration in seconds or minutes, `state_class: measurement` |

Useful later, not yet mapped anywhere (say so here before adding them, and a map key will be added):

| Wanted | Why |
| --- | --- |
| Request budget remaining today | Dashboard gauge against the daily request cap |
| Estimated stored energy or equivalent tank state, with confidence | Compare the model with measured cycle energy |
| Learned standing loss and heating rate | Trend on the dashboard; sanity check against `temperature_rise_c ÷ energy` |
| The solar forecast value the plan used, and its age | Forecast-versus-actual per decision |
| Plan summary as one sentence | Overview tile |

## 4. What the controller can take from this package

| Need | Use |
| --- | --- |
| Measured element power (replaces inference) | `sensor.em_hot_water_power`, `binary_sensor.em_hot_water_element_on` |
| Energy per heating run, for the thermal model | `sensor.em_hot_water_last_cycle` |
| Base load excluding hot water, measured | `sensor.em_house_power` − `sensor.em_hot_water_power` |
| Marginal cost of heating now | `sensor.em_import_price`, `sensor.em_feed_in_price`, `sensor.em_grid_export_power` |
| Whether the inputs can be trusted | `sensor.em_monitoring_health`, `sensor.em_monitoring_quality` |
| Forecast error | Long-term statistics of `sensor.em_solar_forecast_power` and `sensor.em_solar_power` |

The controller's map option `heater_power` (`OPTIONAL_SOURCES` in `config.py`) is the natural place to point at `sensor.em_hot_water_power`. That is a controller change and is not made here.
