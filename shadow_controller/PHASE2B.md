# Phase 2B — Shadow Planner 0.3.0

This is a read-only planning upgrade on draft PR #9, not a heater controller.
Native Schedule and T-Comfort stay untouched. Thermowatt remains 1.3.8 with
30-minute background polling, its existing cooldowns/authentication safeguards,
commands disabled and on-demand refresh disabled. No additional Thermann HTTP
requests are made. Local settings entities write only this integration's options.

## Forecasts and current reality

Forecasting is optional and off by default. Select two optional source entities
in Configure: **published PV forecast** and **published household load forecast**.
The component only reads HA state on its one-minute local timer. It does not
start EMHASS, call a weather service or fetch Forecast.Solar itself.

- EMHASS publishes `sensor.p_pv_forecast` and `sensor.p_load_forecast` with
  `forecasts` lists of `{date, p_pv_forecast}` / `{date, p_load_forecast}`. Units
  must explicitly be W or kW. Custom prefixes/column names need a small owner
  template that normalises to those documented standard keys. Horizon publishing
  must be enabled. No EMHASS deferrable-load or command outputs are consumed.
- Forecast.Solar's supported `forecast_solar.get_forecast` action returns cached
  `watts` data without requesting a new provider forecast. An optional owner
  template can buffer this into a sensor. Only hourly watts, not daily kWh or a
  single "power now" reading, qualifies as a horizon. Owner-buffer examples and
  exact generation-provenance wiring remain unfinished in this handoff.
- **Both inputs require `forecast_generated_at`: an offset-aware ISO timestamp
  of actual forecast calculation/provider update.** EMHASS can republish an old
  horizon; its state `last_reported` is not proof of forecast freshness. Add this
  provenance at the successful forecast/optimisation step or a validated template,
  never by stamping each publish with `now()`. The example does not invent the
  owner's EMHASS run-completion signal. After restart, require a post-start
  generation/update; missing or stale provenance means conservative fallback.
- Prefer the owner's existing EMHASS household-load prediction. With no qualified
  load forecast, PV alone does not become guaranteed net surplus. Forecast use
  is unavailable and the independent fallback remains. No new paid service or
  machine-learning dependency is necessary. Forecast.Solar needs correct panel
  orientation, tilt, 6.6 kWp capacity and 5 kW inverter cap; confirm these locally.

Default uncertainty reduces forecast PV by 25%, increases household demand by
25%, and reserves an additional 0.3 kW for competing loads. A current fresh
GoodWe PV observation can reduce (never increase) the horizon using the measured
PV/expected-PV ratio. Diagnostics show this error/correction. This is a deliberately
simple conservative correction, **not** a trained weather model. It is recomputed
locally; GoodWe history is displayed, but no Recorder-mining or learned daily load
model has been added. Optional weather inputs are not duplicated: Forecast.Solar
or EMHASS already supplies weather-informed predictions.

Gaps, bad units, malformed/oversized series, stale/future/pre-start generation,
nonfinite values or missing load predictions discard the forecast safely. Last
timestamps are end boundaries, never indefinitely held power. Up to 48 hours
and 576 net intervals are accepted; unsupported denser data falls back. A maximum
age of 120 minutes is a starting setting, not evidence the weather is reliable.
Measured net export remains primary for the bounded recent-export scenario
(15 minutes by default); later forecast opportunities cannot postpone the full
grid reservation. Future showers or appliance loads are not guaranteed forecasts.

Primary references: [HA Forecast.Solar](https://www.home-assistant.io/integrations/forecast_solar/),
[cached forecast action](https://www.home-assistant.io/actions/forecast_solar.get_forecast/),
[EMHASS publishing](https://emhass.readthedocs.io/en/latest/publish_data.html) and
[EMHASS publication source](https://github.com/davidusb-geek/emhass/blob/master/src/emhass/retrieve_hass.py).

## Economic and comfort policy

The thermal model is unchanged: 315 L × 4.186 / 3600 ≈ 0.3663 kWh/°C;
the element is a full 3 kW load, not power modulated. Add 30 model minutes when
heat is required. Bottom temperature is not whole-tank usable energy. The native
approximately 8°C thermostat hysteresis and manufacturer protections remain
authoritative; the planner cannot force a satisfied thermostat to heat.

An hour with 2 kW of net surplus and 1 kW off-peak import costs
`2 × 0.092760 + 1 × 0.170200 = AUD 0.355720`, including foregone exports.
Three imported kWh off-peak costs AUD 0.510600: a model difference of AUD 0.154880.
During peak the same mixed hour costs AUD 0.547398, so a no-solar off-peak hour
later can be cheaper. A fixed surplus threshold alone does not decide.

The existing minute-slot plan now ranks actual economic unit cost, not full
solar ahead of all partial-solar slots. The cycle layer separately compares
**continuous full-power windows**, splitting tariff and forecast boundaries and
retaining finite completion time. Waiting candidates are five-minute spaced,
plus tariff/forecast/latest feasible boundaries; this is understandable bounded
search, not a global multi-day optimal-control claim.

- Morning comfort: editable 40°C decision threshold by editable 07:00 Hobart.
  At/above threshold, no additional morning heat is modelled. **Never a 40°C
  storage setpoint.** 35→40°C is about 37 ideal minutes plus the allowance.
- Afternoon: the selected 65–70°C target (70 default) is never silently reduced.
  Weekday storage deadline follows actual afternoon tariff peak. Keep the
  editable nominal household comfort time (16:00 default) visible separately;
  weekend comfort uses that time with no invented peak. The next goal after an
  afternoon deadline is morning, not continuous 70°C maintenance.
- Confirmed Aurora 93 defaults are retained: 0.361878 peak, 0.170200 off-peak and
  0.092760 export AUD/kWh; weekdays 07–10 and 16–21 fixed AEST UTC+10, weekends
  off-peak. Hobart displays these an hour later during DST automatically.
- Reserve sufficient grid time independently of forecasts. When due, start or
  continue the simulated fallback despite economic hold/gap. Insufficient time
  and unavoidable peak use stay visible. Invalid/stale essential data still
  suspends the simulation; native Schedule remains the actual comfort fallback.

## Stateful cycle policy — simulation timings only

| Preference | Recommended / original starting value |
|---|---:|
| Economic start qualification | 10 minutes |
| Sustained economic loss grace | 20 minutes |
| Minimum optional cycle | 30 minutes |
| Minimum optional gap | 30 minutes |
| Solar headroom | 0.3 kW |
| Minimum switching benefit | AUD 0.10 per decision |

An optional start needs fresh distinct observations, useful partial surplus and
enough projected advantage against a feasible grid alternative. A forecast better
window can justify waiting only if the difference exceeds the switching benefit.
Once active, the simulation retains its start, remaining ideal energy and dwell;
it is not a new cycle each minute. Stopping needs a sustained **economic** benefit
from later heating, not just a drop below 3 kW. Short clouds or a small lost
advantage can therefore be ridden through. Loss and start holds reset on gaps;
repeated old samples cannot qualify them.

Comfort overrides ordinary economic dwell/gap. Model target satisfaction, owner
intervention, missing/stale/cloud-failed data and explicitly modelled protection/
fault overrides cancel ordinary simulated dwell. This does **not** claim the
integration can observe a physical fault, antibacterial cycle or real thermostat
satisfaction: those remain unqualified. New observed depletion invalidates a
completed ideal-energy scenario. A newly warmer observation caps its remaining
energy. Session counts reset on restart or changed preferences; no physical
cycle/session is resumed or inferred from persisted state.

The default AUD 0.10 threshold is experimental and deliberately conservative.
With only a 15-minute recent-export assumption, small partial-solar opportunities
may not clear it. Reliable longer forecasts, a larger economic difference, or a
reviewed lower threshold may qualify; fallback never waits for that benefit.
This avoids pretending a short current reading guarantees an hour of solar.

Simulated activity subtracts 3 kW only in a labelled **counterfactual grid** value.
The measured HK1000 reading is never rewritten or increased by 3 kW merely
because a simulated cycle started. Native Schedule may already be using power;
its unverified load cannot be safely de-embedded. A pure test helper demonstrates
that a separately **verified** 3 kW element changes +2 kW export to −1 kW import
without solar disappearing. Future execution needs independent verified power/
state evidence before applying that correction.

## Dashboard, settings and remaining execution limits

Hot Water shows large temperature/recommendation, targets/countdown, planned
start/completion, power flows, whole-cycle costs and history. Settings uses native
number/time/select/toggle controls grouped into Comfort, Solar & Forecasting,
Heating Cycles and Advanced. Current values are in controls; each entry's
recommended/original default and explanation appears once in guidance and its
attributes. Matching defaults are intentionally combined. Accepted planning
ranges are **not newly certified device safety or Manual command limits**.

Controls and Configure both write **one config-entry options store**. Preference
changes validate together, save persistently and recalculate locally without
reloading the heater or requesting cloud data. Invalid changes save nothing.
Changing mappings waits for new source data. Restore recommendations has a
dashboard confirmation and retains mappings, meter direction/verification and
native reference information; it explicitly restores confirmed Aurora tariff
defaults. Custom arbitrary weekly periods and native reference JSON stay in
Advanced Configure; common peak times/prices/weekend policy have native controls.

Keep meter/clock verification, expected native target, tariff profile/custom
periods, provenance/freshness limits and native references advanced-only. Do not
lower freshness gates to mask an unavailable cloud. Diagnostics holds cycle
details, forecast source/error, request counts, assumptions and native-clock checks.

**No executor exists.** Commands and On/resume remain unqualified; 30-minute
status polling cannot confirm short physical cycles or exact thermostat stop
times. Any future execution needs separately approved start/stop/resume/retention
and outage testing, protection evidence, bounded reads/writes and human recovery.
Local solar updates must never cause additional Thermann requests. The source
review in `NATIVE_ON_OFF_REVIEW.md` and supervised test plan still apply.

See [upgrade procedure](UPGRADING_0_3_0.md) and
[synthetic cycle results](CYCLE_SCENARIO_RESULTS.md). Visual rendering on the
owner's actual desktop/mobile and real-history forecast accuracy are not claimed
by isolated CI. No merge, deployment or live testing is authorised here.
