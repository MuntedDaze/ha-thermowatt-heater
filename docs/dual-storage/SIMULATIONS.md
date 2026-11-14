# Offline strategy comparison

Reproduce with `python tools/dual_storage_replay.py --output docs/dual-storage/SIMULATION_RESULTS.json`. The replay calls the production pure policy with a synthetic tank and successful one-minute cloud command readback. Executor/bridge failures are covered separately by mocked integration tests. No heater or cloud connection is used.

All rows use the same conservative **Never schedule heating during peak** policy. The previous strategy means mandatory weekday 70°C; its optional weekend boost is disabled here to isolate the storage requirement. The normal-only strategy disables optional boost. The dual strategy permits verified, economical boost. These are controlled comparisons, not reconstructions of historical bills.

Raw cost includes grid energy and foregone feed-in earnings. Adjusted cost adds hypothetical later off-peak replenishment to the largest end-of-day stored energy among the three strategies in that scenario. This makes the energy trade-off visible; it does not repair a missed pre-peak target or represent an executed extra heating cycle. Rates are synthetic configured values, not current tariff advice.

| Scenario | Raw cost AUD: 70 / 62 / dual | Equal-terminal cost AUD: 70 / 62 / dual | Dual peak temperature °C | Dual commands / modelled HTTP |
|---|---|---|---:|---:|
| strong sun direct 70 | 0.890 / 0.612 / 0.890 | 0.890 / 1.106 / 0.890 | 69.7 | 4 / 106 |
| cloudy off peak | 1.634 / 1.123 / 1.123 | 1.634 / 1.617 / 1.617 | 61.6 | 4 / 106 |
| patchy optimistic forecast | 1.181 / 0.806 / 0.806 | 1.181 / 1.300 / 1.300 | 61.6 | 8 / 119 |
| patchy pessimistic forecast | 1.181 / 0.806 / 0.806 | 1.181 / 1.299 / 1.299 | 61.6 | 4 / 106 |
| unexpected solar after normal | 1.045 / 0.646 / 0.929 | 1.056 / 1.150 / 0.929 | 69.9 | 5 / 109 |
| unexpected daytime draw | 1.271 / 0.997 / 1.271 | 1.271 / 1.482 / 1.271 | 70.0 | 4 / 106 |
| late cold start before peak | 1.163 / 1.163 / 1.163 | 1.163 / 1.163 / 1.163 | 37.9 | 3 / 44 |
| weekend surplus | 0.519 / 0.519 / 0.886 | 1.571 / 1.571 / 0.886 | — | 2 / 102 |
| weekend cloud | 0.519 / 0.519 / 0.519 | 0.519 / 0.519 / 0.519 | — | 0 / 96 |
| ct free required storage | 0.890 / 0.612 / 0.612 | 0.890 / 1.106 / 1.106 | 61.6 | 4 / 106 |
| forecast sun never arrives | 1.642 / 1.140 / 1.140 | 1.642 / 1.626 / 1.626 | 62.0 | 4 / 106 |

Every replay delivers the same specified 2.5 kWh evening draw; the daytime-draw case adds 4 kWh. The late-start case begins at 15:00 AEST with a 30°C tank, so it cannot reach 62°C before 16:00. The lockout wins; this is an explicit storage shortfall, even though this simplified tank can still supply the specified evening energy draw. Real usable shower water is not inferred from that result.

The JSON records peak/off-peak imports, solar self-consumption, lost feed-in earnings, losses, service, initial/final energy, target achievement, forecast error, command timeline and request breakdown for all 33 runs. Conservation tests reconcile input energy, draw, losses and stored-energy change. The 62-to-70 theoretical increment is 2.9302 kWh at 315 L; actual stratification, draws and thermostat behaviour differ.

Strong sun qualifies before the morning peak ends, allowing a direct 70°C start. In the later-solar case, a fresh afternoon forecast update supports a 62-to-70 top-up. Without that update, conservative economics may reject the top-up. Optimistic patchy forecasts cause measured withdrawals and extra commands; the existing optional-command cap limits re-entry and preserves essential heat/OFF capacity. Small forecast-only fluctuations do not withdraw a still measured-qualified boost.

A lower raw cloudy-day bill mostly purchases less stored heat. After equal-terminal replenishment, the difference is small and includes modelled standby loss. On sunny days, extra useful heat can be cheaper than purchasing equivalent energy later, but depends on the configured useful-demand fraction and rates. Weekend solar stores more energy than the baseline strategy; it is not automatically a cash saving for every household.

Limits: a uniform 315 L/3 kW tank, fixed 8°C hysteresis and a simple temperature-dependent loss; no stratification, native protection cycles, command failures, owner intervention or cloud outages. Modelled HTTP assumes successful 30-minute polling, a 20-minute refresh heuristic, pre-command GET/POST and one readback. It is not a vendor token-lifetime claim or a measurement of real requests. Zero modelled peak import is not proof that real software OFF removes electrical power. No annual savings are inferred.
