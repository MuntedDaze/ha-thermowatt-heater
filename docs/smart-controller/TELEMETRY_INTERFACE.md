# Controller backend contract for Fable

Schema version 1. Fable owns dashboards, monitoring packages and reporting;
this branch supplies inputs and backend events only. Entity IDs below are
fresh-install suggestions; resolve existing IDs via their stable unique-ID
suffix and the actual HA registry. Do not assume a Shelly model or installation.

Handoff reviewed against PR #32 commit
`4c078f0802faaafc5d5fcc4264af7894b28fc95c`, `energy_monitoring/ENTITY_CONTRACT.md`.
Neither branch imports the other. Both read the same raw hot-water CT entities.
The dashboard wrappers are explicitly unsuitable as controller inputs.

| Unique-ID suffix | Suggested sensor | Meaning |
|---|---|---|
| `heater_measured_w` | `sensor.thermann_shadow_hot_water_measured_power` | Verified actual circuit W, null when invalid |
| `heater_meter_state` | `sensor.thermann_shadow_hot_water_measured_element_state` | `on`, `off`, `unknown`; independent of mode/setpoint |
| `heater_meter_quality` | `sensor.thermann_shadow_hot_water_meter_quality` | `verified`, `missing`, `unverified`, `power_ambiguous`, `power_implausible`, `unit_invalid`, `stale_or_invalid` |
| `heater_energy_kwh` | `sensor.thermann_shadow_hot_water_circuit_energy` | Normalized optional device counter; resets possible; not integrated estimates |
| `controller_telemetry` | `sensor.thermann_shadow_controller_telemetry` | State = decision reason; attributes = schema below |
| `heater_raw_w` | `sensor.thermann_shadow_hot_water_signed_raw_power` | Signed normalized raw watts for CT verification; invalid sign never authorizes control |
| `expected_completion` | `sensor.thermann_shadow_expected_heating_completion` | timestamp; conservative end of conditional continuous-heating range; unknown when idle/unreliable |
| `next_cloud_poll` | `sensor.thermann_shadow_next_cloud_poll` | timestamp; next clock-aligned fixed background slot only when bridge healthy and schedule known; confirmations can read sooner |
| `cloud_poll_interval` | `sensor.thermann_shadow_cloud_poll_interval` | seconds, duration/measurement; actual fixed bridge interval |
| `next_adaptive_poll` | `sensor.thermann_shadow_shadow_next_adaptive_poll` | timestamp, hypothetical only; flag off means unknown |
| `adaptive_poll_interval` | `sensor.thermann_shadow_shadow_adaptive_poll_interval` | seconds, duration/measurement; shadow suggestion, never actual interval |
| `learned_heating_rate` | `sensor.thermann_shadow_learned_heating_rate` | °C/h from ≥10 clean sessions/≥3 days; unknown until eligible; diagnostic |
| `prediction_confidence` | `sensor.thermann_shadow_heating_prediction_confidence` | `provisional_range` or `unknown`; no claim of tank-wide temperature |
| `request_budget_remaining` | `sensor.thermann_shadow_cloud_request_budget_remaining` | controller estimate over rolling 24 h; unknown if accounting missing; not a vendor quota |

Fable mapping keys: `expected_completion` → expected_heating_completion;
`next_poll` → next_cloud_poll; `poll_interval` → cloud_poll_interval. These
expose the actual fixed schedule while adaptive remains shadow only. Map shadow
entities separately and label them hypothetical. Future learned-rate, confidence
and request-budget keys are proposed here for Fable to add in its own branch.
Fable's interrupted-CT cycle capture remains independent; this backend likewise
invalidates learning after a CT gap and does not invent a missed cycle or bridge
missing data. No Fable file or PR is merged by this work.

Use original meter entities with their native HA power/energy state classes for
Recorder/statistics and Energy Dashboard. The controller's observed summaries
are diagnostic and are not billing totals. No annual savings claims are made.

Telemetry is an event snapshot, updated on a distinct cloud observation,
element/quality change, tariff change, mode, command or decision transition.
Repeated callbacks do not invent samples, energy or events. Keep source CT,
grid and inverter entities in Recorder for the raw timeline. No custom raw DB.

| Attribute object | Fields and semantics |
|---|---|
| root | `schema_version: 1`, `at`: UTC evaluation time |
| `power` | `watts`, `state`, `quality`, `observed_at`: HA receipt/report time |
| `energy` | `circuit_kwh`, `integrated_covered_kwh`, `covered_seconds`, `gaps`, `counter_epochs` |
| `thermann` | `temperature_c`, `target_c`, `mode`, `observed_at`, `status_raw`, `time_basis` |
| `site` | signed `grid_import_kw`, `pv_ac_kw`, `grid_observed_at`, `budget` |
| `site.budget` | `grid_without_heater_kw`, `available_before_heater_kw`, `heater_solar_kw`, `heater_grid_kw` |
| `tariff` | `kind`, `rate_aud_kwh`, `clock`, `feed_in_aud_kwh` |
| `forecast` | source, age, PV correction and load basis; null/missing means unknown |
| `controller` | `state`, `reason`, `wanted`, `operating_mode`, `last_command` (pending or latest resolved intent) |
| `completion` | `state`, `basis`, `continuous_minutes_low/high`, `earliest/latest`, `reported_target_reached` |
| `calibration` | clean `sessions`, `days`, `ready`, `kwh_per_c`, `on_kw`, `affects_control: false` |
| `polling` | opt-in shadow reason/due/counts, actual fixed schedule unchanged; see POLLING_SHADOW.md |

Cloud time is **bridge receipt time**, not verified device-side acquisition.
One bottom probe, target selection, status bit and physical consumption are
different evidence. A local zero reading never confirms an OFF command.
Null means unavailable/unknown, never zero. Grid import is positive once
normalized. Paired power needs source-time skew ≤60 seconds.

Integrated kWh uses trapezoids only across covered, distinct verified reports
within the freshness bound. Gaps/restarts are not filled. Device-counter deltas
may recover total energy across a gap but cannot allocate it to tariffs or
sessions. Counter resets/remaps/impossible jumps start new epochs. Do not add
integrated and cumulative totals together.

Completion is a **conditional continuous-heating range**, not a promised wall
time. With an idle native thermostat or missing meter, no finite completion is
promised. Draws, stratification, hysteresis and stale cloud data widen or remove
certainty. Calibration needs ≥10 clean independent cycles over ≥3 days; it
remains diagnostic until held-out and hardware validation. The compact store
keeps ≤40 sessions, not raw samples; normal saves are at most every 15 minutes,
plus completed sessions and clean unload. Sudden power loss can lose the most
recent unsaved integrated interval; native cumulative energy remains primary.

For household reporting, align time windows and physical boundaries. Heater
marginal cost is not an additive allocation of the household bill. Optional
oven/AC/plugs must never gate the controller. Fable defines their mappings and
avoids double counting downstream devices on a measured parent circuit.
