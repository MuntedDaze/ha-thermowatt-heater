# Synthetic cycle simulation results

Reproduce with `python tools/replay_shadow_cycles.py`. These are counterfactual full-power trials, not real heater operations or guaranteed savings. The benchmark switches immediately and knows synthetic cloud duration. Each case serves the same 6 kWh with zero model shortfall. Positive cost difference means the stateful policy costs more to reduce switching.

| Scenario | Cloud min | Stateful cycles | Benchmark cycles | Switching events avoided | Extra model cost AUD |
|---|---:|---:|---:|---:|---:|
| off_peak | 2 | 1 | 3 | 4 | 0.0077 |
| off_peak | 5 | 1 | 3 | 4 | 0.0193 |
| off_peak | 10 | 1 | 3 | 4 | 0.0387 |
| off_peak | 20 | 1 | 2 | 2 | 0.0774 |
| off_peak | 30 | 1 | 2 | 2 | 0.1161 |
| off_peak | 60 | 2 | 2 | 0 | 0.0774 |
| peak_transition | 2 | 1 | 3 | 4 | 0.0269 |
| peak_transition | 5 | 1 | 3 | 4 | 0.0672 |
| peak_transition | 10 | 1 | 3 | 4 | 0.1345 |
| peak_transition | 20 | 1 | 2 | 2 | 0.2691 |
| peak_transition | 30 | 2 | 2 | 0 | 0.1749 |
| peak_transition | 60 | 2 | 2 | 0 | 0.1749 |
| approaching_deadline | 2 | 1 | 3 | 4 | 0.0077 |
| approaching_deadline | 5 | 1 | 3 | 4 | 0.0193 |
| approaching_deadline | 10 | 1 | 3 | 4 | 0.0387 |
| approaching_deadline | 20 | 1 | 2 | 2 | 0.0774 |
| approaching_deadline | 30 | 1 | 2 | 2 | 0.0774 |
| approaching_deadline | 60 | 1 | 2 | 2 | 0.0775 |

No cloud requests or physical commands. Counts reset with session simulation; native Schedule still owns the actual heater. Separate tests cover missing/failed forecasts, quota/cloud gates, stale readings, observed depletion, comfort overrides and restart. Real thermal response, On/resume, exact thermostat state and forecast accuracy remain unqualified.
