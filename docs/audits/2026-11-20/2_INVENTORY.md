# Settings and code inventory (main d137c4c, Controller 0.17.1 / bridge 1.4.1)

Classes: **REQ** required for approved operation · **SAFE** required for safety ·
**COMPAT** backward compatibility only · **DIAG** diagnostic/developer ·
**DUP** duplicated/redundant · **OBS** unused/obsolete/superseded ·
**ASK** needs owner confirmation.

Method: every key in `config.DEFAULT_OPTIONS` (99) was searched for consumers
outside `settings.py`, `config.py` and `model.py` (the catalogue, parser and
validator). "Read by" means a production module reads the value.

## A. The 33 "Retired" settings

All have no entity, no form, and are kept in saved options; Restore resets the
non-preserved ones to defaults. **32 are genuinely inert. One is not.**

| Key(s) | Read by production? | Still validated? | Class | Note |
|---|---|---|---|---|
| `morning_threshold_c`, `morning_preferred_c` | No | Yes: range + cross-field `morning_preferred_below_minimum` (`config.py:445`, `model.py:260`) | **OBS** | Cancelled by D2. Also an entry migration (`__init__.py:170`) still moves 40 → 42 |
| `morning_preferred_time`, `morning_hard_time` | No | Yes: `morning_times_order` (`config.py:447`) | **OBS** | Cancelled by D2 |
| `morning_time`, `shower_time_enabled`, `shower_time` | No | Yes (time parse, shower range) | **OBS** | Pre-0.7.0 |
| `evening_time` | No | Yes: `afternoon_time_invalid` | **OBS** | |
| `expected_morning_draw_c`, `standing_loss_c_per_hour`, `target_c`, `margin_minutes` | No (`thermal.py` "standing_loss" is a measured value, not this key) | Yes (ranges) | **OBS** | 0.4–0.8 planner |
| `min_solar_kw`, `solar_hold_minutes`, `solar_loss_minutes`, `solar_window_minutes`, `minimum_cycle_minutes`, `minimum_gap_minutes`, `switching_benefit_aud`, `wait_benefit_aud_per_kwh`, `base_load_source` | No | Yes (ranges/choice) | **OBS** | |
| `paused` | No | Yes (bool) | **OBS** | |
| `expected_native_target_c`, `t_comfort_reference_c`, `native_schedule_clock`, `native_schedule_clock_verified`, `native_clock_check_date`, `native_schedule_periods` | No | Yes: `native_reference_invalid`, `native_clock_date_invalid`, `parse_native` JSON | **OBS** | Native Schedule era |
| `controller_bridge_qualified` | Passed into `ControllerConfig` but never decides anything | Yes | **OBS** | |
| `controller_min_heating_minutes`, `controller_min_rest_minutes`, `controller_execution_latency_minutes` | No | Yes: bounds **and** cross-field `rest_longer_than_latency_reserve` (`config.py:354`) | **OBS** | |
| **`export_headroom_kw`** | **Yes** — `executor.py:176`: boost start threshold = `element_kw + export_headroom_kw` (3.3 kW) | Yes | **REQ (mislabelled)** | Finding F1. Not owner-editable today. Must not be deleted with the others |

**Finding F2 — inactive values can reject active edits.** `parse_options`
validates every retired key on every save. A saved combination that fails
`morning_preferred_below_minimum`, `morning_times_order`,
`afternoon_time_invalid`, `rest_longer_than_latency_reserve`,
`native_reference_invalid`, `native_clock_date_invalid` or a malformed
`native_schedule_periods` makes **every** settings change fail with a message
about a field the owner cannot see or edit. No such value is known in the
owner's install (0.7.1 migration clamped the rest/latency pair), so this is a
latent fault rather than an active one, but it is exactly the "historical values
influencing current behaviour" problem.

## B. The 10 Legacy/Developer settings (Advanced → Legacy page)

| Key | Effect today | Class |
|---|---|---|
| `adaptive_polling_enabled`, `event_aware_polling_enabled`, `owner_change_check_minutes` | Only when controller `polling_mode = existing` (v1/v2 plans) | **COMPAT** → OBS once Smart is the only mode (Decision 2) |
| `adaptive_polling_shadow`, `adaptive_poll_heating_minutes`, `adaptive_poll_stable_minutes` | Advisory `PollingShadow` comparison in diagnostics; never affects a request | **DIAG** → OBS |
| `controller_three_state_qualified` | None (`requires_four_states=True` is hard-coded, `executor.py:77`) | **OBS** |
| `weekend_qualify_minutes`, `weekend_sunset_kw`, `weekend_sunset_minutes` | None on control; only size the PV sample buffer (`simple_policy.py:175`) and trigger a policy reset when changed | **OBS** (superseded 0.17.0) |

## C. The 56 active settings

| Key(s) | Class | Note |
|---|---|---|
| `baseline_c`, `normal_storage_c`, `solar_boost_c` | REQ | Owner values 45/62/70 (D1). Choice lists (45/62, 62/70, 62/70) are compatibility for generic installs |
| `optional_solar_boost`, `peak_heating_policy`, `completion_margin_minutes`, `boost_useful_fraction`, `boost_min_saving_aud`, `optional_heat_margin_aud_per_kwh` | REQ | Boost economics; three overlapping "minimum benefit" knobs (DUP-ish, keep — merging changes behaviour) |
| `pause_min_saving_aud` | REQ (generic) | Only acts with a commissioned CT; inert on a CT-free install |
| `daytime_start` | REQ | Start of weekday "daytime" (also Smart overnight boundary) |
| `storage_ready_time` | REQ | Weekend soft deadline (15:30) and flat-tariff days |
| `baseline_start` | REQ | Flat-tariff days; Smart overnight boundary |
| `weekend_solar_heating`, `weekend_pv_start_kw`, `weekend_end_time` | REQ | D3 |
| `solar_cooldown_minutes`, `peak_command_lead_minutes` | SAFE | |
| `pre_peak_observation_minutes`, `low_water_warning_c` | DIAG/warning | Decision 1 |
| `polling_mode` (controller) | REQ, **DUP** with app `polling_mode` | Decision 2 |
| `status_max_age_minutes`, `grid_max_age_seconds` | SAFE | Four overlapping freshness limits (spec §9) — DUP, document, do not merge now |
| `tariff_clock`, `time_zone`, `tariff_profile`, `peak_*` (4), `weekend_peak`, `off_peak_rate`, `peak_rate`, `feed_in_rate`, `tariff_verified` | REQ | |
| `shoulder_rate`, `tariff_periods` | COMPAT (custom tariffs) | Keep: generic installs |
| `forecast_enabled`, `forecast_uncertainty`, `forecast_house_margin_kw`, `forecast_max_age_minutes`, `pv_ac_limit_kw` | REQ | |
| `meter_verified`, `import_positive` | SAFE | Gate all grid use / sign |
| `tank_litres`, `element_kw` | REQ | Planning physics |
| `controller_command_topic`, `controller_four_state_qualified`, `heater_meter_verification`, `ct_free_solar_verification` | SAFE (commissioning) | |
| `controller_max_commands_per_day`, `controller_max_requests_per_day`, `controller_confirmation_timeout_minutes` | SAFE | |
| `controller_notify_service` | REQ | |
| `learned_planning_enabled`, `learning_hardware_qualified` | DIAG (gate never satisfied; synthetic tests only) | ASK-free: keep off; candidate to move to Legacy page |

## D. Entities, pages, sensors

| Item | Class | Note |
|---|---|---|
| Native setting entities | Generated for every non-Retired catalogue key (`settings_entity.py:91`) | Retiring a key removes its entity via the registry clean-up (`naming.RETIRED_SENSORS`, `__init__._remove_retired_entities`) — affects any dashboard/automation using it |
| `sensor.thermann_shadow_morning_availability` | Entity ID **COMPAT**, label **HISTORICAL** | It is the pre-peak low-water assessment (`runtime.py:767`). Keep the ID, change the friendly name only |
| Advanced → Legacy page | COMPAT | Empty it as keys retire |
| `naming.RETIRED_SENSORS` list (incl. `morning_readiness`, `morning_ready_deadline`, `morning_threshold_c`) | COMPAT | Keeps removing old entities on upgrade; keep |

## E. Code

| Area | Class | Note |
|---|---|---|
| `simple_policy.py`, `controller.py`, `executor.py`, `runtime.py`, `forecast.py`, `solar.py`, `targets.py`, `tariff in model.py` | REQ/SAFE | Active |
| `config.parse_options` retired-key validation; `model.Settings` retired fields; `model.validate_settings` retired ranges | **OBS** | F2 |
| `config.LEGACY_MORNING_THRESHOLD_C` + `__init__` 1.1→1.2 migration | COMPAT (harmless) | Becomes OBS when morning keys are no longer validated; keep the migration step itself (entries are versioned) but it can stop touching the key |
| `comfort.morning_availability` | **OBS** | Hard-codes 45@06:00/42@07:00; only a test calls it |
| `native.py`/`parse_native` | OBS | Only validates a retired key |
| `adaptive.make_plan` (v1), `adaptive.event_plan` (v2) | COMPAT | Only for `polling_mode = existing` |
| `polling.PollingShadow` | DIAG | Report uses it |
| `ControllerConfig.bridge_commands_qualified`, `three_state_qualified`, `published_forecasts_enabled` branches | OBS | Dead under `requires_four_states=True` |
| Stale docstrings: `controller.py` header ("STORAGE Manual 70 before the evening peak"), `executor.py` ("three-state topic"), `forecast_unavailable` alert text | OBS text | |
| `thermal.py`, `learning.py`, `performance.py` | DIAG | Read-only; learning never qualified |
| `tools/readiness/fixtures/thermann_shadow_0_2..0_7` | COMPAT (tests) | Frozen releases for upgrade tests — keep |
| `tools/*_replay.py` + JSON results | DIAG | Evidence; keep |

### Bridge (1.4.1)

| Item | Class | Note |
|---|---|---|
| Guarded `TRANSITIONS` (12), `AuthGuard`, confirmation, request budget, poll reuse, proactive refresh | SAFE/REQ | |
| Bare 1.3.11 forms `Manual:70` / `off` in `AUTOMATION_COMMANDS`; `GUARDED_PAYLOADS` | COMPAT | For controllers < 0.9.0. Owner runs 0.16.1 → removable later (command-path change → owner approval) |
| `command_policy: legacy` (full 1.3.8 command set) | COMPAT/ASK | Default `automation`; removal is a command-path change |
| `polling_mode` (app) | REQ, DUP with controller | Decision 2 |
| `adaptive_polling_enabled`, `adaptive_polling_qualified`, `event_aware_polling_qualified` | COMPAT | No effect when app mode is smart/minimum |
| `poll_interval_minutes` + `poll_interval_unit` | REQ (fallback) / COMPAT (unit) | |
| `on_demand_refresh_enabled` | REQ | Needed for pre-command refresh and restart read |
| `OFF_CODES` 16 | COMPAT | Unobserved; 8 is the owner's observed OFF |
| Credentials, tokens, `auth_retry_generation`, private storage | SAFE | Never touched by any cleanup |

## F. Documentation

78 Markdown files outside `docs/history/`. Contradictions with current policy:

| File | Problem |
|---|---|
| `README.md` | Says "Released 0.16.0 / 1.4.0; 1.4.1 in draft PR43" — main is 0.17.1 / 1.4.1 |
| `shadow_controller/COMMISSIONING.md:37,65` | States the morning goals (45 by 06:00, 42 by 07:00) as current |
| `shadow_controller/SETTINGS_AUDIT.md:55–57` | Recommends "Keep — Everyday" for the morning keys |
| `shadow_controller/DASHBOARD_CONTRACT.md:30` | Lists retired morning/afternoon readiness sensors as current |
| `shadow_controller/THERMAL_MODEL.md:81–99` | Plans around the morning minimum |
| `shadow_controller/SIMPLIFIED_STRATEGY.md` §1 | Historical analysis of the morning goals in an active-doc folder |
| `docs/next-major/SETTINGS.md` | Lists every retired key with its old meaning |
| 12 phase folders (`audit-remediation`, `audits`, `cleanup`, `completion`, `configuration`, `dual-storage`, `final-integration`, `next-major`, `pre-review`, `smart-controller`, `solar-delay`, `weekend`) | Each partly current, partly checkpoint; no single source of truth |
| `docs/next-major/OWNER_HANDBOOK.md:68` | Correct ("Old 45-by-06:00/42-by-07:00 warnings are retired") — keep the point |
