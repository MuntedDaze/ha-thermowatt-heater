# Thermann Hot Water Controller 0.6.2 — production candidate

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

## Bridge requirement: 1.3.11

**0.6.2 needs bridge 1.3.11** (bounded confirmation, below). 1.3.10 (PR #15,
deployed) added the `Cmd` 8 mapping and the pre-command refresh described here.

**T3b (13 Nov 2026, bridge 1.3.10, controller disabled):** a stale-status `off`
refreshed once and was POSTed; the app then showed OFF, but 1.3.10 reported
`not_observed_in_immediate_status`. Its only status read came milliseconds after
the POST, before the cloud reported the change, and it never looked again. 1.3.11
treats that as `awaiting_confirmation` and makes at most two follow-up reads
(60 s and 300 s after the POST), never re-sending the POST, and refuses any other
command meanwhile. It ends with `observed_in_status`,
`unexpected_state_after_command` or, after 360 s, `not_confirmed_within_limit`.

### Earlier: 1.3.10

**Control vocabulary: exactly two commands.** `Manual:70` (heating permitted;
the "ON" command) and `off` (parked). No generic `On`, no temperature writes, no
other modes. The bridge's `command_policy: automation` (default since 1.3.9)
refuses everything else before any request.

**T3 (12 Nov 2026, bridge 1.3.9, owner present)** established what OFF reports:

| State | `Cmd` | `WaterHeaterSts` | `T_SetPoint` |
| --- | --- | --- | --- |
| Manual 70 °C | 9 | 33 | 70 |
| software OFF | **8** | 32 | **70** |

MQTT `off` switched the heater OFF and `Manual:70` restored Manual 70 °C and
heating. Two bridge problems followed, both fixed in 1.3.10:

| Problem in 1.3.9 | 1.3.10 |
| --- | --- |
| OFF is `Cmd` 8, but only `Cmd` 16 was known: OFF showed as *Unknown* and a successful `off` as unconfirmed | `Cmd` 8 and 16 are OFF (vendor mode, HA mode, validation, confirmation, guarded resume) |
| A command was dropped (`dropped_status_older_than_60s`) unless sent within a minute of the 30-minute poll | at most **one** bounded status read per command, then every rule re-checked against it |

The controller never reads `Cmd`; it uses the bridge's vendor mode. It never
interprets `WaterHeaterSts` (still unverified) as element activity.

**OFF target rule** (unchanged; T3 saw 70, the first row):

| OFF reports | Controller | Bridge |
| --- | --- | --- |
| 70 °C | parked; resume allowed | accepts `Manual:70` |
| no usable value (missing, or outside 20–75 °C) | parked; resume allowed; 70 is sent explicitly | accepts |
| a usable other value (for example 40 or 65) | **owner override**, notice naming the target; nothing sent | refuses (`refused_target_mismatch`) |

**Bridge re-check on fresh status (1.3.10, automation policy).** The controller
decides from the last poll, up to 30 minutes old. The bridge re-checks the
command against status no older than 60 s (reading it once if needed):
`Manual:70` only from OFF, `off` only from Manual 70 °C. An app change since
the poll is therefore refused with no write and reported, and the controller
treats it as owner control:

| Bridge outcome | Controller |
| --- | --- |
| `observed_in_status` | confirmed |
| `already_in_requested_state`, `refused_mode_mismatch`, `refused_target_mismatch` | **owner override** (`mode_or_target_changed_outside_controller`); nothing was written |
| `refreshing_status`, `submitting`, `submitted_awaiting_status`, `awaiting_confirmation` (1.3.11) | still in progress: a status seen now is not an outcome, however long it takes; the controller's 65-minute timeout is the outer bound |
| `unexpected_state_after_command` (1.3.11) | **owner override** (`unexpected_mode_during_confirmation`) |
| `not_confirmed_within_limit` (1.3.11) | `fault_locked` (`command_not_confirmed`): sent once, never repeated; check the app, then Acknowledge |
| any other `dropped_*`, `refused_*`, `rejected_*` (e.g. `refused_status_refresh_failed`, `refused_cloud_backoff`) | `fault_locked` (`bridge_refused_or_dropped`), never retried |

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
| `heating_requested` / `park_requested` | Wanted, waiting for every gate to pass | All gates pass → one message → `confirming` |
| `confirming` | One persisted intent published | Manual at 70 (resume) or OFF (park) observed → steady; the bridge's fresh status shows an owner change (`refused_mode_mismatch`, `refused_target_mismatch`, `already_in_requested_state`) or a foreign mode → `owner_override`; any other bridge refusal, not applied or timeout → `fault_locked` |
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
- the bridge reports `commands_enabled: true`, and is **1.3.11** (reports its
  refresh budget and confirmation schedule; otherwise `bridge_1_3_11_required`);
- no command awaits confirmation at the bridge (`bridge_confirmation_pending`,
  for example one published by hand);
- cloud health `ok`, auth `authorized`, no backoff.

**Heater state**
- a status exists and is at most one poll interval + 5 min old
  (`heater_status_too_old`); if it is older than 30 s the bridge will read it
  again before the command, so a refresh must remain in the bridge's 24-a-day
  budget (`bridge_refresh_budget_exhausted`, which clears at the next poll);
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

0.6.0 published only within 35 s after a bridge poll, because bridge 1.3.9
dropped anything later. **0.6.1 publishes when the planner decides** (it is
evaluated every minute and on every new poll). With bridge 1.3.10:
- if the status is fresh (≤60 s, for example right after a poll), the bridge
  uses it: one write plus one confirmation read;
- otherwise the bridge reads status once first: three requests in all.

With bridge 1.3.11 a slow cloud readback adds at most two follow-up reads,
so a command costs at most 5 requests. At the default limit of 6 commands a
day that is at most 30 command requests,
inside the 220-a-day request budget and the bridge's 24 refreshes a day.
Normal 30-minute polling is unchanged. Dwell (30 min), the daily command limit
with its comfort reserve, the peak guard and the latency reserve still keep
switching rare. The 30-minute latency reserve is kept as a conservative default;
with 1.3.10 a command normally lands within a minute, so it may be reduced after
the supervised trial. A POST 401/403/429 locks bridge authentication, and that
is never reset automatically.

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
- **Bridge 1.3.11:** 709 tests, including delayed readback (old mode first,
  requested mode at the first or second follow-up), no confirmation, a third
  state, failed follow-ups, POST timeouts, lockouts, refusals while pending,
  restart while pending and the 5-request bound.
- **Bridge 1.3.10 (PR #15):** 670 tests, including `Cmd` 8, the bounded
  pre-command refresh and its failures, and the mode re-check.
- **Bridge 1.3.9:** 519 tests, including the OFF status handling and the guarded
  resume from OFF.
- **Real HA Core check** (CI): a fresh install refuses; one captured `Manual:70`
  from OFF with a reported setpoint of 40; no duplicates; confirmation; re-inspection
  after a reload; disabled sends nothing; no idle storage rewrites.

## Unresolved risks

- **OFF readback is unknown:** what the cloud reports for `T_SetPoint` and
  `WaterHeaterSts` while OFF. The design tolerates any value; T3 observes it.
- **OFF target rule may need revisiting:** if T3 shows that OFF always reports a
  fixed usable value other than 70, every resume pauses for the owner. This is
  safe, but it needs a decision before the trial.
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
