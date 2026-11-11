# Stage 3a — Shadow Planner 0.4.0 (read-only candidate)

**Read-only.** No heater command, Thermann request, native Schedule/T-Comfort,
HA, EMHASS or Tapo change. The Thermowatt add-on stays 1.3.8, byte-identical to
main. Built on the Stage 1 audit (`audit/SYSTEM_AUDIT_2026-11-11.md`) and the owner's
revised Stage 3a requirements. Draft only; owner and ChatGPT review before any
deployment.

## Priorities as implemented

1. Manufacturer safety: never a setpoint below the native target; the native
   thermostat and protections stay in charge; nothing is commanded.
2. Comfort readiness: **42 °C** reading before the morning peak; **65–70 °C**
   (70 default) before the evening peak.
3. **Minimum total economic cost**: imports plus foregone feed-in, for the same
   required energy in every compared plan.
4. Solar self-consumption only when cheaper or equal in cost.
5. Fewer heating blocks, decision changes and cloud requests (the planner adds none).

## What changed

| Area | 0.3.0 | 0.4.0 |
|---|---|---|
| Freshness (Stage 1 F1) | entity `last_reported` (false-stale on unchanged MQTT payloads) | bridge **poll timestamp**; a retained status after restart keeps its real poll time |
| Heater state | not modelled | ON / OFF / UNKNOWN + confidence + basis (`WaterHeaterSts` bit 0 as empirical evidence, 3 kW steps, masked switch-off, stale bit after observed off, optional heater CT) |
| Household load | meter export used as heater surplus | **base load = house − 3 kW when ON**, bounded interval when UNKNOWN; removed exactly once |
| Deadlines | morning 07:00 fixed; afternoon = peak start | morning = **actual morning peak start** (07:00 AEST / 08:00 AEDT), optional earlier shower time; afternoon = **evening peak start** (16:00 / 17:00); weekends use household times (08:00 / 16:00 by default) |
| Morning threshold | 40 °C | **42 °C** (entry migration moves only an untouched 40 °C) |
| Economics | one block now vs one block later, 15 min of measured solar | 15-min slots to the last deadline; exact optimiser over ≤3 blocks with per-deadline energy; *heat now* = start now for ≥ the minimum cycle; fallback with allowance |
| Waiting rule | AUD 0.10 per decision (unreachable without forecasts) | wait only if it saves ≥ **5 c per kWh** that would be heated now, and the fallback stays viable |
| Solar | DC PV, downward-only correction, no clipping | **AC PV**, combined **5 kW AC clipping**, two-way bounded correction; clipped readings are a lower bound |
| Native Schedule | warning string only | native outlook (predicted readiness/cost), thermostat-satisfied detection, read-only **Schedule advisor** |
| Labels | WAIT FOR SOLAR even when not worthwhile | HEAT NOW · HEATING NOW / HEATING LIKELY (NATIVE) · WAIT – CHEAPER LATER · NO HURRY · NO HEATING NEEDED · INSUFFICIENT TIME · DATA UNAVAILABLE · OWNER REVIEW · PAUSED, each with saving, confidence and reason |
| Stability | per-minute flips | only changes between optional economic choices wait 10 min; physical heater state, comfort, gates and "no heating needed" apply immediately |

New sensors (unique IDs `<entry>_<key>`):
- heater element state, heater state confidence;
- base load excluding hot water, PV AC output, solar surplus available to heater;
- next tariff change and next tariff period, current tariff rate;
- morning and afternoon ready deadlines, morning and afternoon readiness;
- saving by waiting, decision confidence;
- native Schedule predicted cost, native Schedule extra cost vs best plan;
- Schedule advisor today.

Retired (they described a non-existent executor): simulated cycle count, stop
count, suppressed switching episodes and simulated session cost. All other
0.2.0/0.3.0 entity IDs are preserved.

## Evidence

**Real-history replay** (`tools/replay_history.py`): a private local copy of the
recorder, read-only, replayed through the actual runtime minute by minute.
Unchanged MQTT payloads are faithfully *not* rewritten. Covers 10 Nov 14:30 →
11 Nov 12:20 (1,311 minutes, all after the HK1000 was commissioned):

| | 0.3.0 as recorded live | 0.4.0 replayed |
|---|---|---|
| Minutes with a recommendation | ≈19 % of 11 Nov 00:04–12:22 (blocked ~10 of 12.3 h) | **98.6 %** (19 min: bridge restarts, genuinely missing) |
| 11 Nov 11:42 (element on, 4.97 kW AC, house 3.9 kW) | WAIT FOR SOLAR, heat-now $1.04 | **HEATING NOW (NATIVE)**: matches cheapest plan, $0.65, 100 % solar |
| 11 Nov 12:02–12:20 | DATA UNAVAILABLE (false-stale) | HEATING NOW (NATIVE) |
| 11 Nov 03:00, 16 °C | blocked | NO HURRY: heat before 04:12 (42 °C by 08:00); fallback fired 03:59 |
| 10 Nov 16:47 (element switched itself off at a 63 °C reading) | — | NO HEATING NEEDED: thermostat satisfied |
| 10 Nov 18:15 (evening peak) | — | WAIT – CHEAPER LATER (off-peak from 22:00) |

The heater estimator spent 361 minutes ON and 950 OFF. After the fixes it
produced no ON/OFF flicker around the 16:46 switch-off. A one-minute kettle-like
spike at 15:24 still briefly reads ON (medium confidence); the decision
stabiliser absorbs it.

**Before/after on identical synthetic inputs:**
[`COMPARISON_0_3_0_VS_0_4_0.md`](COMPARISON_0_3_0_VS_0_4_0.md), generated by
`tools/compare_versions.py` from the frozen installed 0.3.0 code and reproduced
by a test. Highlights:
- 1 kW export at 09:00 (peak): 0.3.0 "WAIT FOR PLANNED WINDOW"; 0.4.0 "WAIT –
  CHEAPER LATER", saving $0.19 (81.7 c/h now vs 43.3 c/h after 11:00).
- 1 kW export at 12:00 (off-peak), flat forecast: 0.3.0 "WAIT FOR SOLAR";
  0.4.0 "HEAT NOW" (nothing cheaper later).
- Partial solar now, full solar forecast later: both wait; 0.4.0 quantifies a
  $0.10 saving.

**Tests:** 777 offline tests (46 new in `tests/test_shadow_v040.py`); real HA Core
smoke on 2026.10.4 and 2026.11.1 with 0.2.0→0.4.0 and 0.3.0→0.4.0 upgrades over
persisted storage, and an unchanged-MQTT-payload freshness check without
`force_update`.

## Findings that contradict or refine Stage 1

1. **Afternoon deadline.** Stage 1 recommended `min(16:00, peak)`. The owner's
   revised requirement is "before the evening peak, dynamically", so 0.4.0 uses
   the peak start: 16:00 standard time, 17:00 daylight time. The 16:00 household
   time is kept for weekends.
2. **Waiting threshold.** Stage 1 proposed $0.015 per kWh of *total* requirement.
   Testing showed this blocks obviously right waits for large jobs (e.g. 06:00
   off-peak grid vs 08:00 solar). The decision is about what would be heated *now*,
   so 0.4.0 uses $0.05 per kWh of the first minimum cycle.
3. **Thermostat temperature.** Stage 1 said the reading is not the thermostat's
   temperature. The replay confirms it (10 Nov: off at a 63 °C reading), and
   0.4.0 now acts on it: storage counts as ready after an in-window switch-off
   until the reading falls >5 °C. The reading *can* reach 70 °C (9 Nov), so the
   70 °C goal stays, with this escape.
4. **Tue 09:20 "step".** Stage 1 called it an appliance. It was PV-output change
   in the meter-less house value before 14:25 (corrected in the audit's §4 text).
5. **Tariff source.** Aurora's 2026–27 schedule says "Any reference to time means
   Australian Eastern Standard Time" (Mon–Fri 7–10 am and 4–9 pm peak, weekends
   off-peak, **no public-holiday exception**). The Economic Regulator's page
   lists the daylight-time evening peak as "4pm–10pm" while also listing
   off-peak "11am–5pm"; that is internally inconsistent and almost certainly a
   typo. 0.4.0 follows the schedule (17:00–22:00 AEDT), configurable if the
   owner's bill shows otherwise.

## Limitations (unchanged or new)

- `WaterHeaterSts` bit 0 is empirical (5/5 transitions), not a manufacturer
  contract; a heater-circuit CT would make the state verified.
- Standing loss (0.2 °C/h) and morning draw (10 °C) are owner-editable
  assumptions, not measured; evening draws are not yet modelled.
- Without a qualified forecast, future solar is zero by design (pessimistic for
  waiting, safe for comfort).
- The Schedule advisor uses today's inputs only; Stage 3c must backtest before
  any window change.
- The EMHASS load forecast still contains heater cycles. 0.4.0 defaults to the
  de-embedded measured base load (`base_load_source: measured_only`).
- One day of clean post-commissioning history. Nothing is fitted to it; the
  bounds and defaults are not tuned to that day.

## Review corrections (ChatGPT review of `ac38eaf`)

1. **Thermostat-satisfied lifetime.** The event is scoped to the **same local
   day's afternoon goal**: it expires at that deadline, resets on a 3 °C reading
   fall (was 5 °C) or new heating, and a switch-off after today's deadline never
   satisfies tomorrow's goal. Readiness reports `satisfied_by_native_thermostat`,
   and the explanation says the reported target was **not necessarily reached**
   (10 Nov: 63 °C reading against a 70 °C target).
2. **Block rules for every strategy.** The optimiser enforces the minimum cycle
   (30 min), minimum gap (30 min) and ≤3 blocks for every plan: best, heat-now,
   single block, single block later. A partial first slot under 7.5 min does not
   count towards a block, and only a job smaller than one cycle may be shorter.
   `constraint_violations()` checks every plan independently; all plans deliver
   the same energy.
3. **Presentation.**
   - *Hypothetical solar surplus if heater off* (renamed) is kept separate from
     measured export. With the element UNKNOWN it shows the conservative lower
     bound with both bounds in diagnostics, and the heat-now cost is a **range**
     (observed case: $0.71–1.14) with confidence capped.
   - Readiness now describes what the **native Schedule** is predicted to achieve
     (`native_predicted_ready` / `at_risk_with_native_schedule` / `unachievable`);
     a hypothetical plan is never shown as guaranteed readiness.
   - The physical heater state is applied **after** the economic stabiliser on
     every tick, so "HEATING NOW (NATIVE)" disappears on the tick the element
     stops. Medium confidence says "HEATING LIKELY (NATIVE)".
4. **Bug found while fixing (2):** the waiting threshold had used the whole first
   block of the heat-now plan. It now uses one minimum cycle from now, so the
   "partial now, full solar later" case correctly waits again ($0.10 saving).

Replay after the corrections: still **98.6 %** availability. 10 Nov 16:47 → NO
HEATING NEEDED (satisfied by the thermostat), and at **17:00 exactly** it moves to
WAIT – CHEAPER LATER (event expired, evening peak). Native heating shows "LIKELY"
until the next poll confirms it (e.g. 11 Nov 11:05 likely → 11:18 now).
