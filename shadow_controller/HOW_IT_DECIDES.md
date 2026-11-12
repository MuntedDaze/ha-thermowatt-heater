# How the controller decides (0.7.0)

Technical reference for the current behaviour. The user guide is [README.md](README.md). The 0.6 reference (bridge contract, state machine, gates) is kept in [docs/history/controller/CONTROLLER_REFERENCE_0_6.md](../docs/history/controller/CONTROLLER_REFERENCE_0_6.md).

## Heating permission is separate from heating

Manual 70 °C only *permits* heating; Thermann's own thermostat decides when the element runs. `permission.py` keeps Manual permitted while heating **now** would be economical, and parks with OFF when it would not.

**How "economical" is judged:**
- **Price now:** the price the 3 kW element would pay *now*, with solar share × feed-in plus the remainder at the current tariff.
- **Price later:** the cheapest **hour** of alternatives before the heat is needed (the next goal). Forecast solar is taken pessimistically; off-peak grid is the other option.
- **Solar is measured excluding the element:** the advisor's base load removes 3 kW while the element is detected on. So the element consuming solar that was being exported never looks like lost solar.
- **Rolling values:** a 10-minute median surplus. A cautious surplus (lower, minus 0.3 kW) is used to *grant* permission; the typical surplus to *withdraw* it.
- **Price margin:** grant when no worse than the alternative (plus a real benefit, or ≥ 50% solar); withdraw only when more than 3 c/kWh worse.
- **Sustained timers:** 10 min, or 5 min during a peak.
- **No cloud requests:** meter and forecast only.

**Behaviour:**
- After the thermostat is satisfied (for example 14:00), Manual stays while the window stays favourable, so the thermostat refills immediately after hot-water use.
- **Peak start:** decided ahead (commands take about a minute). Permission continues into the peak only when solar makes peak top-up cheaper than heating later. On Tariff 93 that needs about 71% solar, roughly 2.1 kW plus headroom. Otherwise it parks before the peak.
- **During a peak:** withdraws after 5 min of sustained disadvantage. That economic park may bypass the minimum-heating dwell; minimum rest still limits permits.
- **Afternoon storage never buys peak-grid heat.** A shower right before the peak may leave storage short; that is accepted.
- **Partial-grid heating** is permitted when cheaper than the alternative.
- **Unknown meter:** no solar is assumed, and it parks before a peak.
- **Unknown planner/meter in the morning window:** the morning fail-safe (below) applies.
- **Commands:** standby permits use the economic command budget (4 of the 6 a day), keeping 2 for comfort, and skip the "thermostat would not call for heat" gate (that is their purpose).

## Morning: preferred 45 °C by 06:00, hard minimum 42 °C by 07:00, every day

- The preferred reserve is planned for when achievable. A shortfall under one whole degree starts nothing.
- After 06:00 only the hard minimum remains; the missed reserve is not chased.
- Inside the 4 h before 07:00, permission is granted or kept while the reading expected at 07:00 is below 42 °C + 1 °C. The expected reading is the current reading minus 0.5 °C/h of cooling. One allowance, not stacked.
- The 0.5 °C/h figure is **provisional**:
  - the planner assumes 0.2 °C/h;
  - the bottom-sensor reading fell about 1 °C/h in recorder history, partly from water use;
  - [THERMAL_MODEL.md](THERMAL_MODEL.md) says how it will be measured.
- Morning heating continues into a morning peak (winter: peak and hard deadline both at 07:00).
- **Fail-safe:** if the planner or meter is unavailable in that window, it permits rather than risk cold showers. Off-peak hours.

## Guest mode and holiday mode

- **Guest (12 h, button):**
  - Manual 70 °C for the period, with economics relaxed;
  - all gates, confirmation and owner rules still apply;
  - starting it releases Hold;
  - expiry or cancel re-inspects before normal control;
  - persisted across restarts;
  - an alert appears if it cannot be applied.
- **Holiday (departure/return datetimes):**
  - parked while away, which keeps OFF's antibacterial and frost protection;
  - no morning goals and no standby permission;
  - in the last 24 h, one return goal at the storage target, so the planner picks the cheapest feasible heating;
  - ends at the return time;
  - dates are validated, never adjusted;
  - **failures are reported:** "heating for your return is blocked" after 30 min of a blocked return heat, the planner's "return goal at risk" when it can't be reached, and "not fully heated for your return" for 2 h after the return while the reading is below the thermostat's restart point. An app change pauses control without cancelling the holiday.
- **Thermann's native Holiday mode is not used.** Its return and protection behaviour is unverified, and the bridge allowlist stays `off` / `Manual:70`. Supporting it later would need a verified, allowlisted command and an owner test.

## Thermal observer (read-only)

`sensor.thermann_shadow_tank_thermal_state` collects evidence: sessions, suspected draws, cooling spans, predicted versus actual. **It never affects control.** See [THERMAL_MODEL.md](THERMAL_MODEL.md).

## When telemetry or cloud control is unavailable

| Situation | Behaviour |
| --- | --- |
| Meter stale or suspect, or no economic comparison | Off-peak: hold the current state. Before **or during** a peak, with Manual on: park at once (never kept through a peak blindly). In the 4 h before 07:00: morning fail-safe permit. Recovery needs 10 sustained minutes again |
| Unknown tariff | Treated as peak |
| Thermann status stale (> one poll + 5 min) | No commands (`heater_status_too_old`) |
| Cloud backoff, quota or auth lock | No commands; alerts. Never retried |
| Command not confirmed | Fault, owner acknowledges (bridge 1.3.11 bounded confirmation) |
| HA restart | Re-inspects; guest and holiday persisted; permission timers restart (10 min) |
