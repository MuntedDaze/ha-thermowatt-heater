# Thermal model: observer now, learning later (0.7.0)

**Status:**
- **Implemented:** a read-only observer that collects evidence and publishes diagnostics.
- **Designed, not implemented:** the adaptive estimator and any use of it for control.

Nothing in this document changes heater commands. The planner still uses the conservative physical model: 315 L at 0.366 kWh/°C (2.73 °C/kWh), the planner's 0.2 °C/h standing-loss assumption, and the 3 kW element. The morning hard-minimum allowance uses the provisional 0.5 °C/h cooling described in [HOW_IT_DECIDES.md](HOW_IT_DECIDES.md).

## Why

Thermann's temperature sensor is **near the bottom** of the tank. Recorder evidence from 9–12 Nov 2026:

| Observation | Value |
| --- | --- |
| Cold, fully mixed tank, 4 h heating | 16 → 49 °C on 12 kWh = **2.75 °C/kWh**, matching physics |
| Heating after water use | **3.4–4.9 °C/kWh**; thermostat satisfied after about 60% of the physical-model energy (19 → 65 °C on 10.7 kWh) |
| Evening showers | reading fell to about **16 °C** while the top of the tank stayed hot |
| Idle cooling of the reading | about 1 °C/h, partly from water use (no clean overnight samples yet) |
| Manual 70 at 62–63 °C | thermostat micro-cycling of 2–7 minutes |

A reading is therefore **not** the temperature of every litre, **not** a measure of stored energy, and **not** proof of shower availability.

## Implemented: `thermal.py` (read-only observer)

**Inputs** — no new cloud requests:
- the existing 30-minute Thermann readings;
- the element state already estimated from the GoodWe/HK1000 meter, plus the `WaterHeaterSts` bit as evidence;
- the Thermann mode;
- the clock.

**Inferred tank states:**

| State | When |
| --- | --- |
| `heating` / `heating_after_draw` | the element is drawing power (meter); "after draw" within 3 h of a suspected draw |
| `settling_after_heating` | heating ended in the last 90 min; whether it ended with Manual still selected (thermostat satisfied) is recorded |
| `draw_suspected` | the reading fell ≥ 3 °C in one poll interval with no heating. Confidence **high** at ≥ 8 °C, **medium** at 3–8 °C, **low** within 90 min of heating (could be the sensor falling back) |
| `settling_after_draw` | within 3 h of a suspected draw; any rebound of ≥ 1.5 °C is added up |
| `stable` | none of the above, with recent readings |
| `unknown` | not enough readings |

Water use is reported as **suspected**, with a confidence. The sensors cannot prove it.

**Evidence collected and persisted** in `.storage/thermann_shadow.<entry>.thermal`, written only when evidence changes and at most every 10 minutes:
- **Heating sessions** (last 30):
  - start, end, minutes and energy (3 kW × meter-detected on-time);
  - start and end readings;
  - observed °C per kWh;
  - after a draw or not;
  - ended with the thermostat satisfied or not;
  - physical-model minutes to 70 °C, for predicted-versus-actual comparison.
- **Suspected draws** (last 30): time, drop, readings before and after, confidence, rebound.
- **Cooling spans** (last 60): undisturbed spans of at least 3 h, with no heating for 90 min and no suspected draw for 3 h. Whole-degree readings are too coarse to judge over 30 minutes.

The Recorder is barely affected: one diagnostic sensor, with a short state string and attributes.

**Entity:** `sensor.thermann_shadow_tank_thermal_state` ("Tank thermal state (estimate)", diagnostic). Its attributes:

| Group | Contents |
| --- | --- |
| `measured` | last reading, reading age, change per hour over the last interval |
| `estimated` | energy in the current session; physical-model upper bound on remaining heating minutes; standing loss in °C/h with sample count |
| `inferred` | last suspected draw; median °C/kWh after a draw versus undisturbed; median actual/physical minutes for satisfied sessions |
| other | `affects_control: false`, recent sessions |

A test enforces that no control module (controller, control plan, permission, executor, strategy) imports the observer.

## Designed, not implemented: adaptive estimator

These would become states of a small estimator that keeps an **effective stored-energy** value rather than trusting the bottom reading:

1. **Stable cooling.** Stored energy falls by a learned, season-dependent loss. Outside temperature would come from a weather entity; there is none today (see DASHBOARD_CONTRACT.md).
2. **Draw.** A sudden bottom drop removes far less energy than a mixed-tank reading implies. Model it as a cold layer of uncertain volume and widen the uncertainty until the reading rebounds or heating resolves it.
3. **Heating after a draw.** Credit the meter-measured energy, about 3 kW × time. The bottom reading rises faster than mixed-tank physics, so it would be bounded by delivered energy, as `SessionTemperature` already does.
4. **Heating an undisturbed tank.** This is close to physics (2.73 °C/kWh); use it as calibration.
5. **Post-heating and post-draw settling.** Learned settling times decide when a reading is trustworthy again.
6. **Thermostat satisfaction.** The element stops while Manual stays selected: the tank is full by the thermostat's own measure, whatever the reading says.

**Possible control uses later**, each needing separate approval:
- shorter planned heating after a draw (about 60% of the physical energy);
- better overnight cooling for the morning minimum;
- crediting heat delivered between polls.

## Before learned predictions may affect control

**Data needed**, gathered during the Stage C trial with the observer running:

| Evidence | Minimum | Why |
| --- | --- | --- |
| Overnight cooling spans while parked | about 15 nights, two seasons | replace the 0.2 °C/h assumption and the 0.5 °C/h provisional allowance |
| Satisfied sessions after a draw | about 20 | the "60% of physical energy" ratio and its spread |
| Undisturbed satisfied sessions | about 10 | the physics baseline on this tank |
| Draws with rebound tracked | about 20 | settling time and draw-detection reliability |
| Morning outcomes (reading at 06:00 / 07:00) | about 30 mornings | whether the allowance is too tight or too loose |

**Validation required:**
- Predicted-versus-actual completion error, measured offline, must stay within the planning margin (30 min) in at least 90% of sessions.
- Learned values only ever **shorten** planned heating within a bounded factor.
- The hard morning minimum keeps the conservative path.
- Owner approval for each control use.

**Useful extra measurement:** mains-water temperature, for example a cheap probe on the cold inlet pipe. Optional, no new hardware required.

## Boundaries (unchanged)

- 30-minute polling.
- No routine cloud refreshes.
- The manufacturer thermostat, antibacterial and frost protection are never bypassed.
- Measured, estimated and inferred values are always labelled.
