# Phase 2B — Shadow Planner 0.3.0 design and review (historical)

> Superseded by [Stage 3a / 0.4.0](PHASE3A_0_4_0.md). The closed-loop day harness
> referenced below (`tools/replay_shadow_days.py`, `DAY_SCENARIO_RESULTS.md`) was
> retired in 0.4.0 because it simulated an executor that does not exist (audit F12).

Read-only planning on draft PR #9, not a heater controller. Thermowatt stays
1.3.8 (byte-identical to main) with commands and on-demand refresh disabled.
Native Schedule and T-Comfort are untouched. No additional Thermann requests.
Codex implemented the Phase 2B core (checkpoint `643ab8a`); Claude continued
from that checkpoint, preserving its work, and completed the items below.

## Architecture

| Module | Role |
|---|---|
| `model.py` | thermal estimate, deadlines (Hobart DST, fixed-AEST tariff), minute-slot plan, independent off-peak fallback reservation, input gates |
| `forecast.py` | read-only adapters: EMHASS `forecasts`, Forecast.Solar `watts`, flat measured baseline; uncertainty, fading measured correction |
| `economics.py` | continuous full-3 kW cycle quote now vs the best feasible later cycle, import + foregone feed-in |
| `cycles.py` | session-local stateful simulation: holds, grace, dwell, gap, comfort override, ideal-energy accounting |
| `decision.py` | plain-language decision code, label and explanation |
| `runtime.py` | reads HA states on a one-minute local timer; diagnostics |
| `settings*.py` + platforms | one catalogue → native controls; one config-entry options store; restore/undo |

Planning and any future execution remain separate: nothing here can command
the heater, and `cycles.baseline_export` accepts only a separately *verified*
element load (0 or 3 kW) for future traces.

## Economics

- Element is always a full 3 kW load. Solar fraction = surplus ÷ 3 kW describes
  the energy source, never modulated power.
- Unit cost = `rate × (1 − f) + feed_in × f`. 2 kW surplus, 1 kW off-peak import
  for an hour: **AUD 0.3557** vs **AUD 0.5106** all-grid. In peak, the same mixed
  hour costs AUD 0.5474, so later all-grid off-peak can be cheaper.
- Quotes integrate minute by minute across tariff and forecast boundaries;
  candidate later starts every 5 minutes plus every boundary, bounded by the
  fallback start. This is understandable bounded search, not global optimisation.
- Measured net export is primary for the next `solar_window_minutes` (15);
  qualified forecasts cover later intervals. Solar headroom (0.3 kW) is deducted
  from **measured** surplus; forecast intervals already carry their own 25 %
  uncertainty and 0.3 kW household allowance.
- With forecasts off, a measured-only solar start is worth at most ≈ AUD 0.058,
  below the AUD 0.10 threshold; a visible warning reports this. The owner's
  threshold is not silently changed.

## Cycle policy (simulation only)

| Preference | Recommended = original |
|---|---:|
| Solar start qualification | 10 min |
| Economic loss grace | 20 min |
| Minimum optional cycle | 30 min |
| Minimum optional gap | 30 min |
| Solar headroom | 0.3 kW |
| Minimum switching benefit | AUD 0.10 |

An optional start needs fresh distinct meter samples showing a sustained benefit
against the best grid alternative, plus the gap. A stop needs sustained economic
disadvantage after the minimum cycle. Comfort (fallback due, latest start, or no
time left) overrides holds, gaps and dwell. Data gates, owner intervention and
qualified protection/fault overrides stop the simulation. Simulated energy is the
**ideal** energy to the goal; the heating-time allowance only moves starts
earlier. Delivered energy is credited between 30-minute polls; a new observed
depletion restarts the goal; a warmer observation caps it. Restart or a changed
preference resets the session.

The meter is never adjusted for simulated heating. The native Schedule may
already be heating inside its window, so a warning flags that the measured grid
may include the real element; it is not de-embedded without verification.

## Review corrections made in this continuation

1. **Options-flow CI failure (`KeyError: 'errors'`).** The real HA flow accepted
   `tariff_periods: "[]"` because Aurora mode ignored the stored custom table; a
   bad table could later activate through the profile select. The table is now
   always validated; the smoke test asserts the re-shown form and unchanged
   options for three invalid inputs.
2. Simulated cycles included the 1.5 kWh time allowance as heat, overstating
   cost by ≈ 30 minutes of heating per cycle. Now ideal energy only.
3. INSUFFICIENT TIME flapped during cycles (based on a 30-minute-old reading);
   it now uses the cycle's credited remaining energy. Thermostat satisfaction is
   no longer shown as DATA UNAVAILABLE. A due fallback starts on the tick before
   its exact time.
4. Solar headroom was deducted twice from forecasts.
5. Forecast.Solar's overnight gap invalidated the whole series; gaps are now zero
   solar. EMHASS custom entity keys and string values are accepted. The measured
   correction uses a 15-minute mean and fades out over 3 hours. A flat measured
   household baseline (Statistics helper) is supported.
6. Restore now keeps the verified tariff contract and pause state, and stores an
   undo snapshot. Settings expose current/recommended/original values.
7. Decisions distinguish the brief's cases with numeric explanations.

## Validation

- **Offline (Python 3.11 locally; CI 3.12/3.13/3.14):** full pytest suite,
  Ruff lint/format, strict mypy for `model.py` and the bridge's read-only module,
  compileall, Bash syntax. Includes economics, forecasts, cycles, decisions,
  restore/undo, DST, dashboard contracts, the cycle report and **23 closed-loop
  synthetic days** (`tools/replay_shadow_days.py`), all reproducible byte for byte.
- **Real HA Core 2026.10.4 and 2026.11.1, `--network none`:** config/options
  flows and validation errors; every settings entity driven through the HA service
  layer (guarded: test driver only, settings domains only) with atomic
  rejections, restore and undo; every dashboard entity reference resolved and every
  markdown template rendered in blocked, planning and forecast states; EMHASS,
  Forecast.Solar + baseline, stale, wrong-unit and missing forecast paths;
  WebSocket/Recorder serialisation; reload/unload; and a genuine
  **0.2.0 → 0.3.0 upgrade** over persisted HA storage (frozen 0.2.0 fixture).
- **Native add-on images (amd64/aarch64) and Supervisor 2026.10.5/2026.11.0
  schema** checks continue to pass on the unchanged 1.3.8 add-on.

## Remaining limitations

- No visual review of the dashboard on the owner's real desktop or phone.
- No real-data forecast accuracy, no confirmation of the owner's EMHASS or
  Forecast.Solar entity shapes, generation signal or array parameters.
- Thermal model is a uniform-tank estimate from the bottom sensor; thermostat
  hysteresis (~8 °C), stratification and standing losses are not modelled.
- 30-minute cloud polling cannot confirm short physical cycles or thermostat stops.
- Closed-loop days assume a hypothetical verified executor that does not exist.

## Before physical control could be considered (separate approval)

Qualify, on the real heater under supervision: a bounded start and a safe stop
that both preserve manufacturer antibacterial and over-temperature protections;
power-resume and programme retention after outages; command confirmation from
readback; a verified element-power signal (so the meter can be de-embedded);
bounded request/confirmation budgets within the cloud quota; and a human recovery
route. See [control and recovery](CONTROL_AND_RECOVERY.md),
[native On/Off review](NATIVE_ON_OFF_REVIEW.md) and
[supervised validation](SUPERVISED_VALIDATION.md).
