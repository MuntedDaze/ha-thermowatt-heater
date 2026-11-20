# Scenario coverage (Controller 0.18.1, app 1.5.0)

Each scenario required by the final owner instruction of 20 November 2026 and
the deterministic tests that exercise it. All tests are offline: real
controller, policy, executor and app (bridge) code with synthetic time, tank,
meters, MQTT and a mocked cloud; no live heater command is possible.

| # | Scenario | Representative tests |
|---|---|---|
| 1 | Weekday heating with forecasts | `test_integration_0_9_0.py::test_live_weekday_cheapest_window_then_park_through_the_real_bridge`; `test_forecast_independence_week.py` (forecast run) |
| 2 | Weekday heating without any forecast | `test_final_release_0_18_1.py::test_weekday_required_62_needs_no_forecast`; `test_audit_regressions_0_9_1.py::test_m4_without_a_forecast_grid_heating_waits_for_the_latest_start`; `test_general_tariffs.py::test_flat_rate_without_forecasts_or_ct_still_requests_normal_weekday_storage`; `test_forecast_independence_week.py` |
| 3 | Weekend with and without measured solar | `test_weekend_window_0_17_0.py` (PV trigger, deadline fallback, warm tank, restart latch); `test_final_release_0_18_1.py::test_weekend_window_without_forecast_starts_62_at_once` |
| 4 | Cloudy, low-solar days | `test_dual_storage_policy.py::test_cloudy_required_weekday_is_62_not_70_with_optional_ct`; week replays (Tue/Sun cloudy, Wed patchy) in `test_final_week_replay.py`, `test_next_major_replay.py` |
| 5 | Overnight thermostat-controlled 45 °C | `test_audit_regressions_0_9_1.py::test_c1_the_overnight_baseline_is_sent_and_held`; `test_operating_policy_0_18_0.py::test_overnight_policy_never_chases_a_morning_bottom_probe_temperature` |
| 6 | Required 62 °C before the evening peak | `test_dual_storage_policy.py::test_ct_loss_and_low_optional_budget_fall_back_to_required_heat`; `test_audit_remediation.py::test_no_ct_never_pauses_running_required_heat_based_on_self_contaminated_grid_export`; week replays (`required_target_reached`) |
| 7 | Qualified 70 °C solar boost | `test_dual_storage_policy.py::test_strong_sun_direct_70_and_unexpected_topup_are_economic`; `test_final_release_0_18_1.py::test_measured_surplus_alone_qualifies_a_boost_without_any_forecast`; `test_final_release_0_18_1.py::test_a_forecast_never_authorises_a_boost_without_measured_surplus` |
| 8 | Peak solar permission and sustained-import withdrawal | `test_audit_regressions_0_9_1.py::test_h1_a_peak_withdrawal_is_not_held_by_the_spacing`; `test_audit_regressions_0_9_1.py::test_n1_manual_70_with_the_thermostat_idle_withdraws_on_real_surplus_only`; `test_dual_storage_policy.py::test_never_peak_overrides_large_export_forecast_and_spacing` |
| 9 | Stale, missing, zero or contradictory readings | `test_circuit_measurement.py` (stale/future/restored/implausible/steady-zero); `test_final_release_0_18_1.py::test_no_measurement_suspends_solar_permission_and_never_invents_surplus`; `test_existing_installation_upgrade.py::test_missing_zero_immature_and_stale_load_use_explicit_nonzero_assumption` |
| 10 | Cloud interruptions and HA restarts | `test_audit_remediation.py::test_real_off_outage_backoff_restart_and_restore_never_bypass_peak`; `test_authentication.py::test_valid_login_and_restart_reuses_tokens`; week replay Friday outage and Saturday restart |
| 11 | Authentication locks, failed confirmation, protective OFF | `test_authentication.py` (locks persist, never auto-reset); `test_command_confirmation_1_3_11.py` (not confirmed, never repeated); `test_solar_delay_0_16_2.py` and `test_independent_review_corrections.py` (protective exit latches once) |
| 12 | Holiday, Hold, app changes, Overrides | `test_controller_0_9_0.py` (hold, holiday, 12-h Override); `test_bridge_1_3_13.py::test_owner_changes_are_never_overwritten`; `test_audit_regressions_0_9_1.py::test_m1_cancelling_the_override_in_a_peak_parks_without_waiting_for_a_poll` |
| 13 | Smart polling failure and automatic fixed recovery | `test_actual_adaptive_polling.py::test_lost_controller_lease_falls_back_without_optimistic_delay`; `test_actual_adaptive_polling.py::test_controller_sends_no_plan_when_the_app_is_not_on_smart`; `test_smart_plan_acceptance_1_4_1.py`; `test_next_major_replay.py` (DST/failure week, expired leases) |
| 14 | DST transitions, tariff boundaries, cooldowns | `test_audit_remediation.py::test_both_dst_change_days_keep_fixed_standard_tariff_and_event_deadline_in_utc`; `test_dual_storage_policy.py::test_peak_lockout_and_return_to_baseline_across_dst_clock_boundaries`; `test_existing_installation_upgrade.py::test_cooldown_does_not_block_essential_off_peak_baseline`; `test_operating_policy_0_18_0.py::test_low_water_is_never_assessed_before_the_morning_peak` |
| 15 | Migration from Controller 0.17.1 / app 1.4.1 | `test_operating_policy_0_18_0.py` (migration verbatim/idempotent, headroom cases, rollback through the frozen 0.17.1 parser); `test_upgrade_1_3_3.py` (tokens, guard, options, MQTT IDs); CI: isolated HA upgrade over persisted storage (`tools/readiness/shadow_ha_checks.py`) and Supervisor update from 1.4.1 options (`tools/readiness/validate_supervisor.py`) |

## Seven-day comparison, forecasts on and off

`tests/test_forecast_independence_week.py` runs the same mixed week (sunny,
cloudy, patchy, optimistic forecast, heavy draws, owner app changes, Friday
status outage, Saturday restart, cloudy Sunday; CT-free) twice, once with
EMHASS forecasts and once with every forecast unavailable.

| | Forecasts available | Forecasts unavailable |
|---|---|---|
| Weekday 62 °C reached (Mon–Fri) | 4 of 5 (Wednesday paused by the simulated owner app change) | the same 4 of 5 |
| Unserved hot-water draw | 0 kWh | 0 kWh |
| Commands during peak | OFF only | OFF only |
| Overnight commands | Manual 45 / OFF only | Manual 45 / OFF only |
| Weekend | 62 window, 45 at 18:00 | 62 window, 45 at 18:00 |
| 70 °C starts | Mon, Wed ×2, Thu, Fri, Sat | Mon, Wed, Thu, Fri, Sat (measured surplus only) |
| Command posts | 24 | 24 |

Before 0.18.1 the forecast-free run made no 70 °C starts at all: a missing
forecast was priced as zero solar after the first 30 minutes, so solar
boosting silently depended on EMHASS. 0.18.1 prices a boost on the qualified
measured surplus when no forecast is available; sustained measured import
still withdraws it.
