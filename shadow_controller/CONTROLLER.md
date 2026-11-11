# Thermann Hot Water Controller 0.6.0 — production candidate

**Status: built and tested offline only.** Nothing has been deployed, no
command has been sent, and no heater, Schedule, T-Comfort or bridge setting has
been changed. A fresh install **cannot** command the heater: automatic control
is off, no command topic is set and the T3 qualification switch is off.
Commissioning gates are in [COMMISSIONING.md](COMMISSIONING.md).

## Control method (owner decision, revised 12 Nov 2026)

| State | Thermann | Who decides the element |
| --- | --- | --- |
| **Heating permitted** | Manual at 70 °C | The Thermann thermostat (8 °C hysteresis), cut-outs and antibacterial logic |
| **Heating parked** | Software **OFF**, mains connected | No ordinary heating. The manufacturer's antibacterial and frost protection stay active |

**Why it changed from 0.5.0** (owner, official app):
- Manual 70 °C keeps its target.
- App OFF and ON keeps 70 °C.
- An **empty** native Schedule made the app's setpoint revert to 40 °C after the
  app was reopened, so the empty-Schedule park was withdrawn.

The owner's guide confirms that OFF keeps antibacterial and frost protection
while mains stays connected.

**Never used:**
- setpoint writes and Schedule writes;
- mains switching;
- disabling protections;
- fallback heating windows.

**The native Schedule is not used.** In Manual and OFF it has no effect, and it
needs no particular configuration. If HA, the cloud or the bridge fails:
- in Manual, the heater behaves as a conventional 70 °C heater;
- in OFF, ordinary heating stays off.

The owner accepts this and recovers in the app: Manual at 70 °C, or ON.

## Bridge requirement: 1.3.9 (PR #12)

| Need | 1.3.8 | 1.3.9 |
| --- | --- | --- |
| Park: `off` → POST `/off`, confirm `Cmd` 16 | yes | yes |
| Resume: `Manual:70` → POST `/manual` with 70 explicitly | unknown payload, ignored | accepted from OFF (whatever OFF reports as its setpoint) or when the target is already 70; other modes with another target refused |
| Status while OFF with a setpoint outside 20–75 °C | **poll fails and the bridge backs off** | published with `setpoint_valid: false` |
| Plain `Manual` with an invalid observed setpoint | would POST it | refused |
| Command outcome in diagnostics (`last_command`) | no | yes |

**What OFF reports as its setpoint has never been observed by the bridge.** The
owner's OFF test fell between polls. The controller therefore **ignores the
setpoint while OFF**, both to classify OFF and to permit a resume. It requires
**Manual at exactly 70 °C** to confirm a resume. If the heater came back at
another target, the controller would pause (`owner_override`) and nothing would
be re-sent. T3 records the real OFF readback.

## Architecture

1. **Planner** (0.4.0): goals, tariffs, solar and forecast, incremental cost,
   block rules and readiness. It never commands. When control is active,
   deadlines are planned 30 min early (the latency reserve).
2. **Planner → controller** (`control_plan.py`): one desired action per command
   slot.
   - Blocks are rounded to the nearest slot.
   - Comfort fallback or insufficient time means permit.
   - Thermostat satisfied means park.
   - Peak guard: park at the last slot before a peak unless the element is
     heating for comfort.
   - Planner unavailable means hold, but still park before a peak.
3. **Controller** (`controller.py`, pure logic): states, gates, intents,
   confirmation, reconciliation and supervision.
4. **Executor** (`executor.py`, HA): the **only** module that may publish
   (`mqtt.async_publish`) or call a service (`notify`); an AST test enforces
   this. It persists state before publishing and writes only on change.

## State machine

| State | Meaning | Leaves by |
| --- | --- | --- |
| `disabled` | Master switch off. Never commands, silent | Owner enables (only when commissioned) |
| `observing` | Waiting for a **new** status after enable, resume, acknowledge or restart | OFF (any setpoint) → `parked`; Manual 70 → `heating_permitted`; anything else (Schedule, Eco, Holiday, Manual ≠ 70) → `owner_override` |
| `parked` / `heating_permitted` | Steady | Planner wants the other state → `*_requested` |
| `heating_requested` / `park_requested` | Wanted, waiting for an eligible poll slot | All gates pass → one message → `confirming` |
| `confirming` | One persisted intent published | Manual at 70 (resume) or OFF (park) observed → steady; definite failure, not applied or timeout → `fault_locked`; foreign mode → `owner_override` |
| `owner_override` | An app change, an unexpected mode or target, or **Hold** | Owner presses **Resume** → `observing` |
| `fault_locked` | Ambiguous or failed command | Owner presses **Acknowledge** → `observing` |

Unchanged from 0.5.0:
- one persisted unique intent at a time, never retried and never re-sent after a
  restart;
- the app takes precedence;
- a restart re-inspects the heater.

## Gates before every command

**Commissioning**
- the command topic is valid;
- T3 is qualified.

**Bridge and cloud**
- MQTT ready and the bridge available;
- the bridge reports `commands_enabled: true` (only 1.3.9 reports this flag);
- cloud health `ok`, auth `authorized`, no backoff.

**Heater state**
- the status is at most 35 s old (just after a poll);
- **resume**: currently OFF (the setpoint is ignored);
- **park**: currently Manual at exactly 70 °C.

**Limits**
- minimum heating and rest periods (30 min; the thermostat may end heating
  earlier);
- at most 6 commands in 24 h, with 2 reserved for comfort;
- the cloud request budget (220/day);
- no unexplained heating in progress.

**For a resume only**
- the reading is at or below 62 °C.

## Protective heating while OFF

Heating while OFF is expected to be the antibacterial cycle or frost
protection. It is detected **before** any decision on each tick and is **never
interrupted**:
- no command is sent while it runs (not even a comfort start);
- the owner is notified once ("protective heating while OFF");
- control resumes when it ends.

## Command timing

Poll-aligned, unchanged from 0.5.0: publish within 35 s of a bridge poll, a
30-min latency reserve, and the peak guard. The cost is usually the POST plus
one confirmation read, but this is not guaranteed. A POST 401/403/429 locks
bridge authentication, and that is never reset automatically.

## Home Assistant interface

- **Switch:** *Automatic heater control* (refuses until commissioned).
- **Buttons:** Hold, Resume, Acknowledge (dashboard asks for confirmation).
- **Sensors:** automatic control state and reason, Thermann mode and target,
  next action, next start and stop, last command, result and time, commands and
  requests in the last 24 h, controller fault.
- **Settings:** command topic, *Bridge commands qualified (T3)*, dwell, daily
  limit, confirmation timeout, request budget, latency reserve, notify service.
  The 0.5.0 *Empty Schedule park confirmed* switch is **removed**; after the
  upgrade it shows as unavailable and can be deleted.
- **Clock warnings:** heater-clock DST warnings and "native programme is the
  comfort fallback" appear only while the native programme is actually in use
  (controller off, or the heater in Schedule). The protective-heating warning is
  never suppressed.

## Evidence (offline)

- **Tests:** 879 pass, including 90 controller tests. OFF-specific coverage:
  - OFF → Manual 70 → OFF with OFF setpoints 0, 40, 65, 70 or none;
  - resume confirmation requires Manual **at 70**;
  - park gates;
  - Schedule, Eco, Holiday and Unknown treated as owner control;
  - app changes OFF→Manual, Manual→OFF and OFF→Schedule never reversed;
  - protective heating while OFF never interrupted, even for comfort;
  - cloud failure while OFF;
  - restart while OFF and while resuming;
  - real bridge `/off` contract;
  - proof that 1.3.8 fails an OFF poll with an out-of-range setpoint;
  - a closed loop with an antibacterial cycle during OFF at three OFF setpoints.

  All 0.5.0 closed-loop days still pass with OFF parking: sunny, cloudy,
  shower, winter, weekend, DST and forecast error.
- **Bridge 1.3.9:** 519 tests, including the OFF status handling and the guarded
  resume from OFF.
- **Real HA Core check** (CI): a fresh install refuses; one captured `Manual:70`
  from OFF with a reported setpoint of 40; no duplicates; confirmation; re-inspection
  after a reload; disabled sends nothing; no idle storage rewrites.

## Unresolved risks

- **OFF readback is unknown:** what the cloud reports for `T_SetPoint` and
  `WaterHeaterSts` while OFF. The design tolerates any value; T3 observes it.
- **API equivalence is unproven:** `/manual` from OFF is assumed to resume like
  the app's power button. T3 tests it. If it does not, `Manual:70` is confirmed
  as not applied and the controller locks, with no retry.
- **Setpoint retention through API OFF:** the controller always resumes with an
  explicit 70 and verifies 70 °C.
- **Element sensing** (`WaterHeaterSts` bit 0) is empirical, and its meaning
  while OFF is unknown. The meter step is the physical check.
- **Antibacterial timing** under daily OFF periods follows the manufacturer's
  own logic; the controller never interferes.
- **Cloud dependency** and the POST auth-lock risk remain; manual recovery is
  accepted.
