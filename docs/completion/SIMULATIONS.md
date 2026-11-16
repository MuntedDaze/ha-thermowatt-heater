# Synthetic hot-water completion evidence

All24 runs use the production policy, executor and bridge with synthetic HTTP/MQTT and denied external networking. These are model results, not observations from the installed heater. The four strategies share the same315L/3kW uniform tank, native8C hysteresis and standing-loss assumptions.

| Scenario | Strategy | Solar kWh | Peak grid kWh | Grid cost AUD | Foregone export AUD | Equal-terminal cost AUD | POST / HTTP |
|---|---|---:|---:|---:|---:|---:|---:|
| clear | required_only | 6.850 | 0.000 | 0.000 | 0.635 | 1.265 | 4 / 106 |
| clear | off_peak_solar | 9.850 | 0.000 | 0.000 | 0.914 | 1.033 | 4 / 106 |
| clear | ct_free_all_solar | 9.750 | 0.000 | 0.000 | 0.904 | 1.040 | 4 / 107 |
| clear | verified_ct_all_solar | 9.750 | 0.000 | 0.000 | 0.904 | 1.040 | 4 / 107 |
| passing_cloud | required_only | 6.850 | 0.000 | 0.000 | 0.635 | 1.265 | 4 / 106 |
| passing_cloud | off_peak_solar | 9.850 | 0.000 | 0.000 | 0.914 | 1.033 | 4 / 106 |
| passing_cloud | ct_free_all_solar | 9.550 | 0.200 | 0.072 | 0.886 | 1.094 | 4 / 107 |
| passing_cloud | verified_ct_all_solar | 9.550 | 0.200 | 0.072 | 0.886 | 1.094 | 4 / 107 |
| sustained_cloud | required_only | 6.850 | 0.000 | 0.000 | 0.635 | 1.265 | 4 / 106 |
| sustained_cloud | off_peak_solar | 9.850 | 0.000 | 0.000 | 0.914 | 1.033 | 4 / 106 |
| sustained_cloud | ct_free_all_solar | 9.250 | 0.550 | 0.199 | 0.858 | 1.184 | 6 / 112 |
| sustained_cloud | verified_ct_all_solar | 9.250 | 0.550 | 0.199 | 0.858 | 1.184 | 6 / 112 |
| appliance | required_only | 6.850 | 0.000 | 0.000 | 0.635 | 1.265 | 4 / 106 |
| appliance | off_peak_solar | 9.850 | 0.000 | 0.000 | 0.914 | 1.033 | 4 / 106 |
| appliance | ct_free_all_solar | 9.417 | 0.333 | 0.120 | 0.874 | 1.130 | 6 / 113 |
| appliance | verified_ct_all_solar | 9.417 | 0.333 | 0.120 | 0.874 | 1.130 | 6 / 113 |
| shower | required_only | 9.900 | 0.000 | 0.000 | 0.918 | 1.539 | 4 / 106 |
| shower | off_peak_solar | 12.900 | 0.000 | 0.000 | 1.197 | 1.307 | 4 / 106 |
| shower | ct_free_all_solar | 12.800 | 0.000 | 0.000 | 1.187 | 1.315 | 4 / 107 |
| shower | verified_ct_all_solar | 12.800 | 0.000 | 0.000 | 1.187 | 1.315 | 4 / 107 |
| weekend | required_only | 0.000 | 0.000 | 0.000 | 0.000 | 1.795 | 0 / 98 |
| weekend | off_peak_solar | 9.750 | 0.000 | 0.000 | 0.904 | 1.040 | 2 / 103 |
| weekend | ct_free_all_solar | 9.750 | 0.000 | 0.000 | 0.904 | 1.040 | 2 / 103 |
| weekend | verified_ct_all_solar | 9.750 | 0.000 | 0.000 | 0.904 | 1.040 | 2 / 103 |

Equal-terminal comparison hypothetically replenishes all runs to70C with later off-peak grid energy. It is separate from required62C target achievement and is not real bill saving. All24 cases reached the specified normal weekday target in this model; no cloud-command confirmation failed. Weekend normal62C is not required. Real thermostatic behavior, stratification, draw timing and vendor latency remain unverified.

The sustained cloud produced0.55kWh peak heater import in both CT-free and measured-CT modes; the appliance event produced0.333kWh. Metering does not itself remove the10-minute tolerance. Required-only and off-peak-only strategies had no peak heater import in these runs. The recorded grid cost and lost feed-in value are separate; more solar heat is not automatically cheaper at equal service.

## Money at risk and command failure

At a nominal3kW and the illustrative model peak rate0.361878AUD/kWh,10minutes entirely on grid uses0.5kWh and costs0.181AUD. A further6minutes would add0.3kWh/0.109AUD;16minutes total would cost0.290AUD. These are scenario calculations, not physical cutoff bounds. A failed cloud exit can last longer. The controller reports unresolved time, nominal energy and cost using the highest observed import price, and alerts rather than replaying or unlocking commands.

A separate dispatch experiment compares10-,5- and2-minute withdrawal at equal useful heat. Faster OFF saves money when sun fails persistently and may lose useful solar or add switching when clouds pass. We retain the owner-selected10-minute continuous rule and do not invent an additional rapid-import threshold from synthetic cents alone. See `../smart-controller/SIMULATION_RESULTS.json` and `../../tools/controller_replay.py`.

## Existing full-week failure and API evidence

The refreshed eight-week fixed/adaptive comparison retains actual request-category accounting. CT-free fixed30 used713 HTTP attempts versus447 for qualified event-aware60 (37.3% fewer); verified CT used732 versus483 (34.0% fewer). Each pair preserves its model cost and command-count outcomes. These are synthetic replay comparisons, not real session qualification or household savings. Fixed60 alone can miss useful fresh-temperature decisions and is not the starting recommendation.

Additional full-week suites cover missed targets after heavy late draws, owner changes, CT outages, bridge/cloud failures, lost adaptive leases and rejected token refresh. A rejected refresh stays locked with no further HTTP; lower counts after failure are not savings. See the refreshed `../pre-review/WEEK_RESULTS.json`, `../pre-review/FAILURE_RESULTS.json` and `../final-integration/WEEK_RESULTS.json`.

The45 focused upgrade regressions separately cover continuous real-report spans, pending START/OFF, split status/diagnostic messages, actual mocked bridge and controller restarts, owner overrides, missing diagnostics, auth/backoff/budget blocks, CT failure, cooldown overlap, morning probe risk and exact legacy counter migration. Independent review has no outstanding material findings; final-head CI and physical commissioning are distinct gates.
