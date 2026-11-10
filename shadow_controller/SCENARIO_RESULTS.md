# Representative shadow scenarios

Synthetic fixed snapshots using owner-confirmed defaults, not actual heater tests or guaranteed outcomes. Solar-qualified case assumes the observation hold; separate runtime tests prove its ten-minute gate. No services, cloud requests or heater operation.

| Scenario | Bottom °C | Goal °C | Deadline (Hobart) | Recommendation | Fallback start | Heating min incl. margin | Estimated plan AUD |
| --- | ---: | ---: | --- | --- | --- | ---: | ---: |
| Morning already ready | 42 | 40 | 10 Nov 07:00 | shadow_no_modelled_topup | — | 0.0 | 0.000 |
| Morning below threshold | 35 | 40 | 10 Nov 07:00 | shadow_wait_for_window | 10 Nov 05:53 | 66.6 | 0.567 |
| Summer cloudy | 50 | 70 | 10 Nov 17:00 | shadow_wait_for_window | 10 Nov 14:03 | 176.5 | 1.502 |
| Summer sustained solar | 50 | 70 | 10 Nov 17:00 | shadow_solar_opportunity | 10 Nov 14:03 | 176.5 | 1.444 |
| Winter depleted | 17 | 70 | 09 Jun 16:00 | shadow_wait_for_window | 09 Jun 09:01 | 418.3 | 4.118 |
| Winter afternoon | 63 | 70 | 09 Jun 16:00 | shadow_wait_for_window | 09 Jun 14:38 | 81.3 | 0.692 |
| Weekend | 50 | 70 | 14 Nov 16:00 | shadow_wait_for_window | 14 Nov 13:03 | 176.5 | 1.502 |
| Late shortage | 17 | 70 | 10 Nov 17:00 | shadow_shortfall | 10 Nov 16:50 | 418.3 | 0.085 |

The late-shortage case cannot fit the modelled heat before the deadline; it warns rather than claiming comfort. Winter-depleted heating uses only necessary peak energy when off-peak time is insufficient. Normal cloudy cases wait only until the reserved fallback. A 70°C request inside thermostat hysteresis may not initiate heat; the estimate never defeats that protection.

Tests also cover DST transition Sundays, tariff boundaries, missed polls, quota lockouts, stale grid data, restarts, unchanged-report solar holds, owner intervention and saved settings. Real owner-history replay and live command semantics remain unverified.
