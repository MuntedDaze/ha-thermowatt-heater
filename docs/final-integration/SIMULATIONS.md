# Offline week and economic comparisons

Reproduce with `python tools/final_week_replay.py --output docs/final-integration/WEEK_RESULTS.json`
after installing development requirements. `tests/test_final_week_replay.py`
recomputes all eight weeks and checks the committed JSON, energy conservation,
service, requests, owner detection and outage/restart behaviour. No vendor,
owner HA or MQTT endpoint is contacted: the actual controller/executor and bridge
worker use synthetic HTTP, states, MQTT, time and private in-memory persistence;
socket/network access is denied. This is stronger than an advisory poll count,
but is still a simulation, not measured real-world savings or commissioning.

## Same week, four polling strategies

Each CT configuration runs fixed 30 minutes, fixed 60 minutes, the previous
shadow advisory while actually polling at fixed30, and real adaptive scheduling.
All use the same policy and required demand. The old shadow never controlled
HTTP, so its actual cost/request results equal fixed30. Its hypothetical read
count is not a closed-loop savings estimate. Fixed60 deliberately retains the
normal 45-minute temperature freshness limit rather than weakening it for a
better benchmark; frequent unknown status and a refused command are real costs
of that choice.

The uniform 315 L/3 kW tank has native 8°C hysteresis, 0.2°C/hour loss and rounded
cloud probe readings. Every run begins at 45°C and serves the same 45 kWh draw
energy: 2.5 kWh each morning/evening, plus Thursday 4 and Friday 6. Replenishment
to equal terminal storage is priced at a hypothetical later off-peak 0.1702
AUD/kWh; it is not an executed cycle or a repair to a missed peak deadline.
Costs include marginal grid cost and foregone export income, exclude fixed
whole-house charges, and are not an annual bill estimate. Rates are synthetic
owner-example inputs, not current universal retail prices.

Monday is sunny, Tuesday cloudy with optimistic forecast, Wednesday patchy,
Thursday has heavy use, Friday loses CT reports for an hour and cloud status
15:30–16:30 AEST, Saturday restarts HA/controller/history, Sunday is cloudy.
Wednesday includes a five-minute app change and a separate two-hour owner
Manual55 intervention at peak; the simulated owner explicitly resumes control.
All configured strategy requests retain Never-peak policy; owner intervention
and failed/unconfirmed OFF remain protected instead of promising zero power.

## Request, cost and detection results

| CT | Strategy | Actual HTTP | Intents / POSTs | Peak / off-peak grid kWh | Heater solar kWh | Equal-terminal cost AUD | Persistent owner detection min |
|---|---|---:|---:|---:|---:|---:|---:|
| no | fixed_30 | 713 | 20 / 20 | 0.667 / 19.763 | 36.620 | 7.0018 | 15 |
| no | fixed_60 | 380 | 20 / 19 | 2.745 / 18.441 | 35.863 | 7.4589 | 45 |
| no | previous_shadow | 713 | 20 / 20 | 0.667 / 19.763 | 36.620 | 7.0018 | 15 |
| no | actual_adaptive | 730 | 20 / 20 | 0.721 / 19.663 | 36.666 | 7.0086 | 15 |
| yes | fixed_30 | 740 | 30 / 30 | 0.489 / 7.318 | 48.593 | 5.9299 | 15 |
| yes | fixed_60 | 408 | 29 / 28 | 0.538 / 11.872 | 43.891 | 6.3035 | 45 |
| yes | previous_shadow | 740 | 30 / 30 | 0.489 / 7.318 | 48.593 | 5.9299 | 15 |
| yes | actual_adaptive | 624 | 30 / 30 | 0.489 / 7.330 | 48.581 | 5.9308 | 5 |

With a CT, adaptive used **624 vs 740 HTTP attempts (15.7% fewer)**, with the
same 30 POSTs and about AUD 0.0009 higher equal-terminal cost in this week. The
persistent change happened closer to its poll: detection was 5 vs 15 minutes.
That is phase-dependent, not a guaranteed improvement. Worst healthy status age
rose from 31.7 to 39.7 minutes, and maximum age including cloud outage rose from
67.7 to 80.7. Thus fewer requests also meant older observations.

CT-free adaptive used **730 vs 713 (2.4% more)**: its 30-minute cap cannot earn
the longer quiet CT interval, while pre-decision and fresh command-prior reads
cost requests. POSTs stayed 20, owner detection 15 minutes and adjusted cost was
AUD 0.0068 higher. Do not enable this feature on the promise of CT-free savings.
It remains disabled pending real request/freshness review. Fixed60 used fewer
requests but owner detection took 45 minutes and temperature was unavailable for
2,362 CT-free / 2,280 measured minutes. Adaptive unknown minutes were 45 / 36;
fixed30 were 44 / 23.

| CT | Strategy | Login | Refresh | Status | Pre-command GET | POST | Confirmation |
|---|---|---:|---:|---:|---:|---:|---:|
| no | fixed_30 | 1 | 335 | 327 | 10 | 20 | 20 |
| no | fixed_60 | 1 | 169 | 160 | 12 | 19 | 19 |
| no | previous_shadow | 1 | 335 | 327 | 10 | 20 | 20 |
| no | actual_adaptive | 1 | 334 | 336 | 19 | 20 | 20 |
| yes | fixed_30 | 1 | 335 | 325 | 19 | 30 | 30 |
| yes | fixed_60 | 1 | 172 | 159 | 20 | 28 | 28 |
| yes | previous_shadow | 1 | 335 | 325 | 19 | 30 | 30 |
| yes | actual_adaptive | 1 | 258 | 278 | 27 | 30 | 30 |

Discovery is zero because the harness supplies its synthetic known device.
Refresh counts use the existing conservative 20-minute heuristic; they do not
establish the vendor’s token lifetime. Failed attempts are counted. Commands
still need a fresh exact prior and observed confirmation; adaptive reads never
shorten auth/backoff/quotas. Lost scheduling lease returns to fixed polling.

## Service, failures and prediction limits

All runs served the specified draw energy, but that is a simple energy model,
not guaranteed shower temperature. CT-free runs missed the 62°C daytime target
on patchy Wednesday (maximum about 61.1°C). CT-measured runs reached it on all
five weekdays. Friday’s late heavy draw still left a peak-boundary shortfall:
about 50.45°C / 4.23 kWh below 62 without CT, 59.05°C / 1.08 kWh below with CT.
Earlier target achievement must not conceal this later storage deficit. The
JSON records each day’s maximum, actual 16:00 temperature and shortfall.

The status outage left nonzero modelled peak grid energy: 0.72 kWh CT-free
adaptive / 0.49 measured. It is classified as unverified lockout, not successful
routine peak scheduling or measured electrical OFF. Notifications include
`peak_lockout_unverified`, cloud faults, stale status and (when mapped) CT loss.
Fixed60 also records a refused/unposted intent. Restart resumes inspection and
retains history; no old intent is replayed. No strategy observed the five-minute
transient app change. Owner holds last until explicit resume.

Forecast error is recorded as solar kW MAE in every JSON row. For measured
adaptive there were eight uninterrupted, unchanged-target completion samples.
The MAE of the deliberately broad **latest continuous-heating bound** versus
actual target crossing was about **138 minutes** (fixed30 137); it is not an
accurate arrival-time point forecast. The upper envelope is conservative and
single-probe/hysteresis assumptions are large. CT-free completion is unknown,
not assigned a synthetic prediction. Interruption/draw/target change invalidates
an evaluation sample. These results do not validate real thermal accuracy.

No clean learning sessions qualified in this disrupted week: changes, incomplete
starts and sparse/short native cycles were excluded. The new learned-planning
flags stay false. Separate synthetic held-out regression datasets exercise the
eligibility/fit gate; only real clean independent observations and hardware
qualification can authorise learning. Standing loss and useful extra boost heat
are not identified by this single-probe simulation.

## Four-state economic comparison retained

The existing [33-run strategy comparison](../dual-storage/SIMULATIONS.md) and its
JSON remain reproducible regression evidence, now also tested with the integrated
policy. They compare mandatory70, required62 and economical62/optional70 using
equal service and visible terminal replenishment. On the synthetic cloudy case,
raw costs were AUD 1.634 / 1.123 / 1.123, but adjusted costs were 1.634 / 1.617 /
1.617: most of the apparent raw reduction purchased less stored heat. In the
unexpected-later-solar case, dual adjusted cost was 0.929 vs required62 1.150,
conditional on future usefulness/rates/forecast coverage. It is not a universal
saving or evidence that extra storage was physically useful in this household.

The earlier comparison models successful commands/request counts; this week
uses the actual mocked worker including failures and backoff. Keep their HTTP
metrics distinct. Neither includes native protective cycles, stratification,
actual vendor delays, tariff contract eligibility, or electrical isolation.
Only authorised physical observation can qualify production behaviour.

