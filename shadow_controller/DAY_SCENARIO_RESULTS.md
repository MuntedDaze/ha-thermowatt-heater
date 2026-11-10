# Closed-loop synthetic day scenarios

Reproduce with `python tools/replay_shadow_days.py`. Each minute runs the real planner chain (forecast adapter → evaluate → cycle policy → decision) with a **hypothetical, verified** executor following the simulated cycle. No such executor exists and the heater is never operated. Assumptions: uniform 315 L tank, 0.3663 kWh/°C, full 3 kW element; no hot-water draw-off or standing loss during the window; Thermann cloud poll every 30 minutes, whole-degree readings (goal met within 0.5 °C); native Schedule heating not modelled (executor would replace it); default owner settings unless the case says otherwise.

| Scenario | Comfort met | Tank at end °C | First start | Cycles | kWh | Solar kWh | Cost AUD | All-grid AUD |
|---|:-:|---:|:-:|---:|---:|---:|---:|---:|
| partial_2kw_measured_only | yes | 69.7 | 14:40 | 1 | 5.4 | 3.103 | 0.679 | 0.919 |
| surplus_1kw_forecast | yes | 69.7 | 14:40 | 1 | 5.4 | 1.502 | 0.803 | 0.919 |
| surplus_2kw_forecast | yes | 70.0 | 10:59 | 1 | 5.5 | 3.655 | 0.656 | 0.946 |
| surplus_3kw_forecast | yes | 69.9 | 10:32 | 1 | 5.45 | 5.417 | 0.512 | 1.196 |
| surplus_4kw_forecast | yes | 69.9 | 10:02 | 1 | 5.45 | 5.45 | 0.506 | 1.483 |
| clear_morning_cloudy_afternoon | yes | 69.7 | 09:56 | 1 | 7.2 | 7.199 | 0.668 | 1.839 |
| cloudy_morning_sunny_afternoon | yes | 69.7 | 12:14 | 1 | 7.2 | 7.2 | 0.668 | 1.225 |
| forecast_sun_fails | yes | 69.8 | 14:03 | 1 | 7.25 | 0.204 | 1.218 | 1.234 |
| household_load_spike | yes | 70.1 | 10:30 | 1 | 7.35 | 5.886 | 0.795 | 1.538 |
| solar_drop_mid_cycle | yes | 69.6 | 10:50 | 1 | 9.0 | 7.5 | 0.951 | 1.628 |
| depleted_winter_tank | yes | 69.6 | 09:23 | 1 | 18.15 | 7.143 | 2.794 | 3.444 |
| warm_morning_tank | yes | 45 | — | 0 | 0.0 | 0.0 | 0.0 | 0.0 |
| cold_morning_tank | yes | 40.1 | 05:53 | 1 | 1.85 | 0.0 | 0.315 | 0.315 |
| target_65 | yes | 65.0 | 10:31 | 1 | 5.5 | 5.5 | 0.51 | 1.214 |
| target_70 | yes | 70.1 | 10:30 | 1 | 7.35 | 7.35 | 0.682 | 1.538 |
| winter_weekday | yes | 69.7 | 09:56 | 1 | 7.2 | 6.422 | 0.74 | 1.264 |
| weekend_summer | yes | 69.5 | 09:21 | 1 | 7.15 | 7.017 | 0.674 | 1.217 |
| dst_start_morning | yes | 40.1 | 05:53 | 1 | 1.85 | 0.0 | 0.315 | 0.315 |
| dst_end_morning | yes | 40.1 | 05:53 | 1 | 1.85 | 0.0 | 0.315 | 0.315 |
| stale_forecast | yes | 69.8 | 14:03 | 1 | 7.25 | 7.189 | 0.677 | 1.234 |
| cloud_poll_outage | yes | 70.1 | 10:30 | 2 | 7.35 | 7.35 | 0.682 | 1.538 |
| insufficient_off_peak_time | **NO** | 44.6 | 14:00 | 1 | 9.0 | 8.681 | 0.86 | 1.532 |
| no_deembedding_naive_meter | yes | 69.6 | 10:29 | 1 | 9.0 | 9.0 | 0.835 | 1.829 |

## Decision sequences

- **partial_2kw_measured_only** — Steady ~2 kW net surplus, forecasts OFF (defaults). 09:00 wait_for_cheaper_window → 14:40 heat_now_partial_solar → 16:28 no_topup_required
- **surplus_1kw_forecast** — Steady ~1 kW net surplus, accurate forecast. 09:00 wait_for_forecast_solar → 14:36 wait_for_cheaper_window → 14:40 heat_now_partial_solar → 16:28 no_topup_required
- **surplus_2kw_forecast** — Steady ~2 kW net surplus, accurate forecast. 09:00 wait_for_forecast_solar → 10:49 qualifying_solar → 10:59 heat_now_partial_solar → 12:49 no_topup_required
- **surplus_3kw_forecast** — Steady ~3 kW net surplus, accurate forecast. 09:00 wait_for_forecast_solar → 10:22 qualifying_solar → 10:32 heat_now_partial_solar → 12:21 no_topup_required
- **surplus_4kw_forecast** — Steady ~4 kW net surplus, accurate forecast. 09:00 wait_for_forecast_solar → 09:52 qualifying_solar → 10:02 heat_now_solar → 11:51 no_topup_required
- **clear_morning_cloudy_afternoon** — Sunny until 12:30 then 80% cloud; forecast knows. 09:00 wait_for_forecast_solar → 09:46 qualifying_solar → 09:56 heat_now_partial_solar → 10:29 heat_now_solar → 12:20 no_topup_required
- **cloudy_morning_sunny_afternoon** — Heavy cloud until 12:00, then clear; forecast knows. 09:00 wait_for_forecast_solar → 12:04 qualifying_solar → 12:14 heat_now_solar → 14:38 no_topup_required
- **forecast_sun_fails** — Forecast clear all day; reality 85% cloud. Fallback must hold. 09:00 wait_for_forecast_solar → 13:59 wait_for_cheaper_window → 14:03 begin_grid_fallback → 16:28 no_topup_required
- **household_load_spike** — Clear day; 2.5 kW appliance 12:00-13:00 not forecast. 09:00 wait_for_forecast_solar → 10:20 qualifying_solar → 10:30 heat_now_solar → 12:00 heat_now_partial_solar → 12:57 no_topup_required
- **solar_drop_mid_cycle** — Clear day with a 30-minute 90% cloud at 11:30. 09:00 wait_for_forecast_solar → 10:40 qualifying_solar → 10:50 heat_now_solar → 11:30 heat_now_grace_period → 12:00 heat_now_solar → 13:50 no_topup_required
- **depleted_winter_tank** — Winter weekday, 20°C tank at 09:00; little solar. 09:00 wait_for_forecast_solar → 09:16 qualifying_solar → 09:23 heat_now_partial_solar → 15:26 no_topup_required
- **warm_morning_tank** — 45°C at 00:30: above the 40°C morning threshold. 00:30 no_topup_required → 07:00 wait_for_cheaper_window
- **cold_morning_tank** — 35°C at 00:30: off-peak top-up to 40°C by 07:00. 00:30 wait_for_cheaper_window → 05:53 begin_grid_fallback → 06:30 no_topup_required → 07:00 wait_for_cheaper_window
- **target_65** — Afternoon storage target 65°C, clear day. 09:00 wait_for_forecast_solar → 10:21 qualifying_solar → 10:31 heat_now_solar → 12:21 no_topup_required
- **target_70** — Afternoon storage target 70°C, same clear day. 09:00 wait_for_forecast_solar → 10:20 qualifying_solar → 10:30 heat_now_solar → 12:57 no_topup_required
- **winter_weekday** — Winter clear day, peak at 16:00 Hobart. 09:00 wait_for_forecast_solar → 09:46 qualifying_solar → 09:56 heat_now_partial_solar → 12:20 no_topup_required
- **weekend_summer** — Saturday: off-peak all day, comfort time 16:00. 09:00 wait_for_forecast_solar → 09:11 qualifying_solar → 09:21 heat_now_partial_solar → 10:29 heat_now_solar → 11:44 no_topup_required
- **dst_start_morning** — Sun 4 Oct 2026 (clocks forward at 02:00), 35°C at 00:30. 00:30 wait_for_cheaper_window → 05:53 begin_grid_fallback → 06:30 no_topup_required → 07:00 wait_for_cheaper_window
- **dst_end_morning** — Sun 5 Apr 2026 (clocks back at 03:00), 35°C at 00:30. 00:30 wait_for_cheaper_window → 05:53 begin_grid_fallback → 06:30 no_topup_required → 07:00 wait_for_cheaper_window
- **stale_forecast** — Forecast published 3 h old: ignored; conservative fallback. 09:00 forecast_unavailable_conservative_fallback → 14:03 heat_now_solar → 15:32 heat_now_partial_solar → 16:28 no_topup_required
- **cloud_poll_outage** — No new Thermann poll 11:00-13:00 (data unavailable). 09:00 wait_for_forecast_solar → 10:20 qualifying_solar → 10:30 heat_now_solar → 11:16 data_unavailable → 13:00 qualifying_solar → 13:10 heat_now_solar → 14:51 no_topup_required
- **insufficient_off_peak_time** — 20°C at 14:00 summer weekday: cannot reach 70°C by 17:00. 14:00 insufficient_time → 17:00 no_topup_required
- **no_deembedding_naive_meter** — Clear 4 kW day, executor IGNORES its own 3 kW load. 09:00 wait_for_forecast_solar → 10:19 qualifying_solar → 10:29 heat_now_solar → 10:30 heat_now_partial_solar → 13:29 no_topup_required
