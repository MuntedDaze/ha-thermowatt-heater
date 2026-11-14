# Backend contract for four-state dashboards

Controller 0.10.0, event **schema 2**. This extends the
[PR #33 schema-1 contract](../smart-controller/TELEMETRY_INTERFACE.md).
Fable owns `energy_monitoring/**`, its tests/workflow and dashboard/reporting.
This change supplies backend entities and a contract only; it does not modify,
merge or install Fable's files. Reference: its [reviewed contract at 4c078f0](https://github.com/MuntedDaze/ha-thermowatt-heater/blob/4c078f0802faaafc5d5fcc4264af7894b28fc95c/energy_monitoring/ENTITY_CONTRACT.md).

## Raw source boundary

`heater_power` is the raw exclusive circuit active-power entity in W or kW.
`heater_energy`, when available, is the same channel's raw cumulative Wh or kWh.
Both projects read these entities independently. Never use absolute-value
`sensor.em_hot_water_power`, the dashboard's integrated energy substitute, oven
or AC channels as control authority. Negative raw watts remain visible for
commissioning and never authorise optional heating. Raw acquisition cadence at
unchanged zero must be verified; an HA receipt within 120 seconds is required,
not inferred from the cloud or a template heartbeat. A mapped stale CT becomes
a fault, not CT-free operation. No mapping is the supported CT-free mode.

## Entity mapping

Resolve actual HA registry IDs using the stable suffix
`<config_entry_id>_<suffix>`; users can rename entities. Suggested new IDs below
use the retained `thermann_shadow` prefix. All previous entity IDs remain.

| Unique-ID suffix | Suggested sensor suffix after `sensor.thermann_shadow_` | Meaning |
|---|---|---|
| `thermann_mode`, `thermann_target`, `temperature` | `thermann_mode`, `thermann_target`, `bottom_temperature` | Actual cloud-reported mode, target and bottom reading; not physical ON/OFF |
| `policy_state` | `policy_wanted_state` | Desired physical state: `off`, `baseline` (45), `normal_storage` (62), `storage` (70), or `hold` |
| `normal_storage_target_c` | `normal_storage_target` | Configured normal target; default 62°C |
| `solar_boost_target_c` | `solar_boost_target` | Configured optional target; default 70°C |
| `desired_temperature` | `desired_thermostat_temperature` | Planned requested °C, unknown when no target is available; not achieved temperature or proof a held request was sent |
| `heating_requirement` | `heating_requirement` | `required`, `optional`, `baseline`, `park` or `owner_override` |
| `boost_eligibility` | `solar_boost_eligibility` | Eligibility of this optional opportunity; separate from user enable |
| `boost_reason` | `solar_boost_reason` | Rejection/selection code, such as disabled, measurement missing, hysteresis, time, economic margin or budget reserve |
| `planned_heat_kwh` | `planned_heating_energy_estimate` | Nominal-model gap to desired target, not measured energy or a billing total |
| `peak_heating_policy` | `peak_heating_policy` | Chosen Never / verified solar-only policy |
| `optional_boost_enabled` | `optional_solar_boost_enabled` | `on`/`off` user choice |
| `circuit_measurement_mode` | `circuit_measurement_mode` | `ct_free`, `measured` or `meter_fault` |
| `heater_measured_w`, `heater_raw_w` | `hot_water_measured_power`, `hot_water_signed_raw_power` | Qualified W versus signed raw diagnostic W; unknown is never zero |
| `heater_meter_state`, `heater_meter_quality` | `hot_water_measured_element_state`, `hot_water_meter_quality` | Physical evidence `on`/`off`/`unknown`, with reason for invalidity |
| `heater_energy_kwh` | `hot_water_circuit_energy` | Normalised optional native cumulative counter, resets possible |
| `expected_completion` | `expected_heating_completion` | Timestamp, conservative end of a conditional continuous-heating interval; unknown when idle/unreliable |
| `next_cloud_poll`, `cloud_poll_interval` | `next_cloud_poll`, `cloud_poll_interval` | Actual fixed clock slot / seconds duration; guarded reads may happen sooner |
| `next_adaptive_poll`, `adaptive_poll_interval` | `shadow_next_adaptive_poll`, `shadow_adaptive_poll_interval` | Hypothetical shadow timestamp / seconds, never actual schedule |
| `learned_heating_rate`, `prediction_confidence` | `learned_heating_rate`, `heating_prediction_confidence` | Target/model-specific diagnostic °C/h and provisional/unknown confidence |
| `request_budget_remaining` | `cloud_request_budget_remaining` | Estimated controller rolling-24h headroom; unknown if accounting incomplete, not a vendor quota |
| `controller_telemetry` | `controller_telemetry` | State = decision reason; attributes = event snapshot |

`storage` retains its historical physical 70°C meaning in persisted state and
events. Display it as SOLAR_BOOST by role, or owner override when requested for
that reason. `normal_storage_62` is an executor operating state; do not confuse
executor state with policy desired state or actual cloud target. Configurable
roles may share a physical state, so use `heating_requirement` and actual target
together. The historical `storage_target_c` / Afternoon storage target entity
now means configured normal target. No old entity is renamed for that change.

Fable's existing map keys can use `expected_completion` → the completion sensor,
`next_poll` → actual fixed next poll and `poll_interval` → actual fixed duration.
The latter must be labelled fixed while adaptive remains shadow-only. Four-state
plan/boost/policy, learned-rate, confidence and budget keys are additions proposed
for its own later mapping change; no claim that PR #32 already maps them.

## Event attributes

Schema 2 retains the old `power`, `energy`, `thermann`, `site`, `tariff`,
`forecast`, `controller`, `completion`, `calibration` and `polling` objects. The
new `heating_plan` is an extensible object. Consumers must handle unknown/null,
missing optional fields and future extra reason codes.

| Object | Additions / semantics |
|---|---|
| root | `schema_version: 2`; `at` UTC evaluation time |
| `heating_plan` | `desired_target_c`, `heating_role`, `normal_target_c`, `boost_target_c`, `baseline_target_c`, `planned_heat_kwh`, `peak_heating_policy`, `optional_boost_enabled`, `circuit_measurement_available` |
| `heating_plan` eligibility | `boost_eligible`, `boost_reason`; if calculated, `boost_extra_kwh`, `boost_expected_saving_aud`, `boost_standby_allowance_aud`, `boost_useful_fraction`, `boost_cost_aud_per_kwh`, `boost_heating_hours` |
| `heating_plan` required plan | Available `best_start`, `latest_start`, `soft_target`, `next_peak`, `cost_now`, `cost_best`, `heating_hours`; datetime fields ISO strings, costs estimates per kWh where named as such |
| `completion` | Adds `measured_kwh_since_anchor` when covered energy can reduce remaining time; only fresh reported temperature sets `reported_target_reached` |
| `calibration` | Adds `target_c`; current model cohort only, `affects_control: false` retained |
| `polling` | Adds desired/reported targets; `before_decision_normal_62`, `before_decision_boost_70`, `near_completion_normal_62`, `near_completion_boost_70` identify consequential advisory reads |

`boost_eligible` describes the current plan computation, not permission to bypass
executor guards. An already-running boost may be held without a new eligibility
calculation. Owner holds/cloud gates can prevent the wanted target from being
sent. Display the controller fault and last command result alongside the plan.
`peak_lockout_unverified` is a fault/notification, never verified zero power.

Events update on meaningful status/element/quality/tariff/intent/decision changes;
they are not a raw sample stream. Keep the original power/grid/energy sensors in
Recorder for independent observations. Derived energy estimates have no HA
energy measurement state class. Do not add integrated energy to the cumulative
meter total or use marginal hot-water attribution as an additive household bill.

## History and predictions

Measured v2 sessions retain the actual target, tank litres and nominal power.
Calibration filters that cohort and needs ≥10 independent clean cycles over
≥3 days. Old target-unknown v1 sessions remain unclassified. CT interruptions,
target changes, invalid temperatures and implausible slopes invalidate the
affected learning interval. Gaps are not interpolated. Counter deltas across
gaps cannot recover missing tariff/session allocation. Fable's independently
fixed interrupted-CT cycle capture is neither imported nor replaced here.

Completion uses a fresh bottom probe and currently verified active element,
with only covered measured energy since a matching anchor reducing the range.
It may use diagnostic calibrated bounds, never claim an achieved tank-wide
temperature. CT-free, idle/native hysteresis, draws and missing data cannot
produce a reliable promised wall time. Actual bridge polling remains fixed;
the shadow comparison can propose an earlier observation near 62/70 decisions
or completion, but confirmation/backoff/auth/budgets remain bridge-owned.
