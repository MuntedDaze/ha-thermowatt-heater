# Compatible hot-water interfaces

One authority chooses heat (`simple_policy.py`); one arbiter persists intent
before sending (`controller.py`/`executor.py`); the installed bridge alone owns
cloud HTTP, authentication, bounded confirmations and request scheduling.
EMHASS, dashboards and future bathroom/household systems must not add another
heater command path or vendor client.

| Producer / input | Consumer contract | Quality / failure rule |
|---|---|---|
| Existing GoodWe/HK1000 grid power | Saved `sources.grid`, raw W/kW and saved sign | Real report timestamp, post-boot, nonrestored and within saved freshness; stale/unavailable withdraws optional peak permission |
| Existing EMHASS PV forecast | Saved `forecast_pv`, dated series and original `forecast_generated_at` | Existing generation age/order/unit/horizon checks remain; republication does not refresh provenance |
| Existing EMHASS load or household mean | Saved `forecast_load`, independently bounded demand | Zero/missing/stale/insufficient coverage uses explicit provisional flat floor; no invented daily profile |
| Optional future exclusive heater CT | Existing `heater_power`, optional `heater_energy` and commissioning record | Independent of dashboard templates; no missing-to-zero conversion, no automatic downgrade after CT failure |
| Existing HA controller entities | Read-only state, decision, mode, target, confidence, tariff, forecasts, command/budget and telemetry | Preserve entity IDs; unknown physical operation remains unknown without verified circuit evidence |
| Owner-authorised HA controls | Existing master switch, Hold/Resume/Acknowledge,12-hour Override and configuration | Same arbiter/commissioning/owner gates; never direct unguarded MQTT/cloud calls |

The missing-load fallback is **max(1.0 kW, a valid current whole-house reading)**,
then the existing uncertainty and appliance margin are applied.1.0 kW is an
explicit engineering assumption, not learned household demand. A near-zero
point invalidates the load series for this decision and uses that conservative
flat floor across the valid PV horizon. Existing positive load forecasts retain
their values. A Statistics helper needs valid source and at least75% coverage
to contribute its mean; its window duration is not independently known, so it
still reports provisional quality, never established24-hour history. PV generation
checks are independent. The current whole-house value may include heater draw;
retaining that value is conservative and no CT/Tapo sums are added to it.
See the [official Statistics attribute definitions](https://www.home-assistant.io/integrations/statistics/).

New read-only entities (all retain the `thermann_shadow` naming prefix):

- `sensor.thermann_shadow_solar_boost_status`: WAITING / ACTIVE / STOPPING / COOLDOWN.
- `sensor.thermann_shadow_solar_boost_cooldown_ends`: confirmed withdrawal plus15min.
- `sensor.thermann_shadow_protective_off_waiting_time`: unresolved seconds.
- `sensor.thermann_shadow_unconfirmed_off_nominal_energy_exposure` and
  `sensor.thermann_shadow_unconfirmed_off_nominal_cost_exposure`: nominal power
  times elapsed unresolved duration; price is the highest observed import price
  during that exit. These are scenario estimates, without energy/statistics classes.
- `sensor.thermann_shadow_solar_exit_request_reserve`:10-request local planning reserve.
- `sensor.thermann_shadow_household_forecast_quality`: published/covered-provisional/
  assumed-provisional/unavailable quality; detail includes the assumed floor.
- `sensor.thermann_shadow_morning_hot_water_availability`: latest-probe risk/unknown
  evidence for45C06:00 and42C07:00; no claim of continuous whole-tank achievement.

The existing controller telemetry includes the durable protective exit, original
pending intent, cooldown, solar-session authority, gate failures and recovery
guidance. An app intervention, Hold, disable or restart retires optional-session
authority; a protective-exit requirement is retained until legitimately resolved.

Routine local evaluation uses fresh grid/CT events plus the existing one-minute
tick. It does not make an HTTP request per evaluation. Existing activation/restart
demand-refresh, bridge-owned confirmation, one expiring adaptive-plan lease and
fixed fallback are preserved. We did not introduce10–15-minute active-session
polls: real grid import can be evaluated locally without that extra request cost.
Adaptive/enlarged quiet intervals remain separately qualified/default-off.

Future household reports may consume these data and the existing native HA
Energy statistics. Future bathroom automation has no heater authority. Parent/
child circuit attribution and any forecast improvement must avoid adding leaf
appliance use to an already measured whole-house total. This release implements
neither a new whole-home forecasting engine nor bathroom control.
