# Thermann Hot Water Controller 0.5.0 — production candidate

**Status: built and tested offline only.** Nothing has been deployed, no
command has been sent, and no heater, Schedule, T-Comfort or bridge setting has
been changed. A fresh install **cannot** command the heater: automatic control
is off, no command topic is set, and two commissioning confirmations are false.
The owner's commissioning gates (A–E in [COMMISSIONING_0_5_0.md](COMMISSIONING_0_5_0.md))
come before any real operation.

## Control method (owner decision, 11 Nov 2026; T1 passed)

| State | Thermann | Who decides the element |
| --- | --- | --- |
| **Heating permitted** | Manual at 70 °C | The Thermann thermostat (8 °C hysteresis), cut-outs and antibacterial logic |
| **Heating parked** | Schedule with an **empty** weekly programme | No ordinary heating. Antibacterial and frost protection stay active |

There is no `/off`, no setpoint write, no Schedule write and no fallback heating
window. If Home Assistant, the cloud or the bridge fails, the heater keeps its
last mode:
- in Manual it behaves as a conventional 70 °C heater;
- in parked Schedule, ordinary heating stops.

The owner has accepted occasional cold water and manual recovery in the
official app.

## Architecture: four responsibilities

1. **Planner** (0.4.0, unchanged in substance): goals, tariffs, solar and
   forecast, incremental cost, block rules, readiness. It never commands.
   - When control is active, comfort deadlines are planned **30 minutes early**
     (the *execution latency reserve*). Readiness then reads
     `planned_by_controller`, not the native-Schedule outlook.
2. **Planner → controller boundary** (`control_plan.py`): turns advice into one
   desired action (`permit` / `park` / `hold`) per command slot.
   - **Plan blocks** are rounded to the nearest slot, half a poll interval.
   - **Comfort** fallback or insufficient time means permit (comfort first).
   - **Thermostat satisfied** means park.
   - **Peak guard:** at the last slot before a peak, park unless the element is
     heating for comfort.
   - **Planner unavailable** means hold, but still park before a peak.
3. **Controller** (`controller.py`, pure logic): the state machine, gates,
   intents, confirmation, reconciliation and supervision.
4. **Executor** (`executor.py`, HA side):
   - builds observations from existing HA states;
   - persists controller state **before** publishing;
   - publishes the single MQTT message the controller returns;
   - sends notifications.

   It is the only module that may publish. A test enforces that: no other
   module can call `publish`/`async_call`, and the executor calls exactly one
   `mqtt.async_publish` and only `notify` services.

**Bridge (separate PR #12, 1.3.9).** Adds the guarded `Manual:70` payload: it
enters Manual only when the fresh observed target is already 70 °C and sends
70 explicitly; any other target is refused with no request. The bridge also
reports each command's outcome (`last_command`) in its diagnostics. With bridge
1.3.8, `Manual:70` is an unknown payload: no request is made, and the
controller locks at the next poll. `Auto` is the existing `/auto` contract.

## State machine

| State | Meaning | Leaves by |
| --- | --- | --- |
| `disabled` | Master switch off. Never commands; still tracks an unconfirmed command | Owner turns the switch on (only when commissioned) |
| `observing` | Waiting for a **new** status after enable, resume, acknowledge or restart | Schedule/70 → `parked`; Manual/70 → `heating_permitted`; anything else → `owner_override` |
| `parked` / `heating_permitted` | Steady | Planner wants the other state → `*_requested` |
| `heating_requested` / `park_requested` | Wanted, waiting for an eligible command slot; `reason` shows the blocking gate | All gates pass → publish → `confirming` |
| `confirming` | One persisted intent is published | Observed expected mode → steady; definite failure, not applied or timeout → `fault_locked`; foreign mode → `owner_override` |
| `owner_override` | App change, unexpected mode/target, or the owner's **Hold** | Owner presses **Resume** → `observing` (re-inspects) |
| `fault_locked` | Ambiguous or failed command | Owner presses **Acknowledge** → `observing` (re-inspects) |

**Rules that always hold:**
- **No duplicates.** One intent at a time, each with a unique persisted ID; it is
  never re-sent, including after a restart.
- **The app wins.** A mode or target change the controller did not cause puts it
  in `owner_override`. Automation never reverses it.
- **Restarts re-inspect.** After a restart the controller reconciles from a new
  status. An unresolved intent is resolved from observed status only.
- **Disabled means disabled.** A disabled controller never changes the heater
  mode. Re-enabling inspects the actual state first.

### Gates checked before every command (all must pass)

**Commissioning**
- the command topic is valid;
- the empty-Schedule park is confirmed;
- the bridge is qualified (T3).

**Bridge and cloud**
- MQTT ready and the bridge available;
- the bridge reports `commands_enabled: true`;
- cloud health `ok`, auth `authorized`, no backoff or cooldown.

**Heater state**
- the status is at most 35 s old (just after a poll);
- the current mode is as expected and the target is exactly 70 °C.

**Limits**
- minimum heating and rest periods (30 min each; the thermostat may end heating
  earlier);
- at most 6 commands in 24 h, with the last 2 reserved for a comfort start and
  its park;
- the cloud request budget for 24 h (220);
- no unexplained heating in progress.

**For a start only**
- the reading is at or below 62 °C (70 − hysteresis). Above that the thermostat
  would not call for heat, so no command is wasted.

## Command timing: poll-aligned (evaluated)

Bridge 1.3.8/1.3.9 silently drops a command whose observed status is older than
60 s, or which is itself older than 30 s. The bridge polls every 30 minutes.

- **Chosen: poll-aligned.** The executor is triggered by the
  *Last successful poll* state change, and publishes only within 35 s of a poll.
  - **Cost:** usually the POST plus the bridge's single confirmation read; the
    access token was just refreshed by that poll. This is **not guaranteed to be
    two requests**: a 401 on the confirmation read adds a refresh and a replay.
    A POST 401/403/429 locks bridge authentication, and that is never reset
    automatically.
  - **Latency:** up to one poll interval.
- **How latency is handled:**
  - comfort deadlines are planned 30 minutes early;
  - plan blocks are rounded to the nearest slot (at most about 15 minutes of
    misalignment, roughly 0.75 kWh moved between solar and grid, about $0.06 per
    transition);
  - the peak guard parks at the last slot before a peak.

  In closed-loop simulations every scenario met its afternoon readiness
  (≥65 °C) with zero peak-grid minutes.
- **Rejected:**
  - An **on-demand pre-read**: it needs `on_demand_refresh_enabled` (an add-on
    change), costs about 3–5 more requests per command, and is limited to one
    per 5 minutes. The evidence above does not justify it.
  - **Faster polling**: it doubles cloud traffic.

  Either can be added later as a bounded option if supervised data shows missed
  opportunities.

## Physical behaviour handled

- **Permission is not heating.** The element state comes from the 0.4.0
  estimator (`WaterHeaterSts` bit 0 plus a 3 kW house-load step).
  - If Manual is confirmed, the reading is ≤60 °C and the element has been off
    for 15 min, an alert is raised. Nothing is re-sent.
- **Thermostat cut-off** ends a session (the satisfied event leads to a park);
  modes are never toggled to beat hysteresis.
- **Sensor overshoot (T1).** About 0.19 kWh moved the bottom reading from 55 to
  62 °C. During heating and for 90 minutes afterwards, the planning temperature
  is capped at the start reading plus delivered energy ÷ 0.366 kWh/°C, plus
  1 °C. Long heating is unaffected: 4 h moved the reading 16 → 49 °C, matching
  the uniform-tank figure.
- **Unexplained heating while parked** may be antibacterial, frost protection or
  a non-empty programme. It is never interrupted, writes wait until it ends, and
  the owner is notified.
- **Hot-water draws** during a session: the planner re-plans every minute and
  the controller follows at the next slot.

## Home Assistant interface

- **Switch:** *Automatic heater control* (master; refuses to turn on until
  commissioned; off never changes the heater mode).
- **Buttons** (dashboard asks for confirmation): *Hold heater (owner override)*,
  *Resume automatic control*, *Acknowledge controller fault*.
- **Sensors:**
  - *Automatic control state* (attributes: reason, recovery guidance, gate
    failures, pending intent, desire, observation);
  - *Automatic control reason*, *Controller fault*;
  - *Thermann mode*, *Thermann target*;
  - *Next intended action*, *Next heating start*, *Next heating stop*;
  - *Last command*, *Last command result*, *Last command time*;
  - *Commands in last 24 hours*, *Cloud requests in last 24 hours*.

  The existing 0.4.0 sensors (readiness, element state, cost, solar) remain.
- **Settings (Controller group):**
  - command topic;
  - the two commissioning confirmations;
  - minimum heating and rest periods;
  - maximum commands per day;
  - confirmation timeout;
  - cloud request budget;
  - latency reserve;
  - optional notify service.

  Commissioning values are kept by *Restore recommended*.
- **Notifications** use HA persistent notifications plus the optional notify
  service:
  - command failure, not applied, timeout, unexpected mode, override and lock;
  - stale status, cloud fault and missing measurements;
  - comfort at risk;
  - unexplained heating;
  - Manual but not heating;
  - *control restored*.

  Condition alerts repeat at most every 6 h and are dismissed when resolved.

## Evidence (offline)

- **Tests: 852 pass locally**: the 789 existing tests plus 63 new controller
  tests. They cover:
  - fresh install unable to command;
  - topic validation;
  - disabled operation and re-enable inspection;
  - start and park;
  - already in the desired mode;
  - poll-slot waiting;
  - hysteresis;
  - thermostat cut-off;
  - dwell and daily budgets with the comfort reserve;
  - request budget and accounting loss;
  - cloud, auth, backoff, bridge-disabled, MQTT and temperature gates;
  - dropped or refused commands;
  - wrong target;
  - late cloud application;
  - never applied;
  - lost confirmation timeout;
  - unavailable-during-command;
  - foreign mode during confirmation;
  - HA restart while confirming and while steady;
  - bridge counter reset;
  - duplicate MQTT status;
  - owner app change and hold;
  - acknowledgement and restoration notice;
  - unexplained heating;
  - Manual-not-heating;
  - stale and missing data;
  - publish failure;
  - planner-boundary rules incl. peak and comfort;
  - T1 overshoot cap;
  - empty Schedule;
  - option bounds and preservation;
  - latency reserve;
  - the **real 1.3.8 bridge** (guarded payload harmless, `Auto` contract);
  - a 1.3.9 contract model (end-to-end with a draw, late application, lost
    command, app change mid-session).
- **Closed loop through the real 0.4.0 advisor** (bridge and thermostat model):

  | Day | Commands | Heating | Readiness |
  | --- | --- | --- | --- |
  | Sunny weekday, shower 08:30 | Manual 10:01, Auto 14:02 | 11.7 kWh, all on solar (feed-in cost, $1.08) | 49 °C at 08:00 (no morning heating), 69 °C at 17:00 |
  | Cloudy weekday | Manual 12:31, Auto 16:32 | Off-peak grid | 70 °C at 17:00 |
  | Shower at 07:30 | Comfort start at the 07:31 poll | Comfort before the 08:00 peak | 45 °C at 08:00 |
  | Winter weekday, weekend, DST-start Sunday, sunny-forecast-but-cloudy day | 1–4 each | Zero peak-grid minutes | ≥65 °C by the deadline |

- **Real-history replay (private recorder copy, 10 Nov 14:25 → 11 Nov 20:50,
  read-only):**
  - Planner availability was **98.7 %**.
  - In the open-loop controller dry-run, the real heater followed its native
    Schedule, so the counts are not closed-loop. The dry-run gave 2 commands on
    10 Nov and 8 on 11 Nov; the 16 °C overnight event and re-planning against a
    heater that ignored the plan inflate the 11 Nov count. That led to the
    comfort reserve in the daily budget.
  - The replay found a defect, now fixed. On 10 Nov (polls at :04/:34),
    "insufficient time" would have kept Manual across the 17:00 peak start. The
    peak guard now parks whenever the element is not heating at the last slot.
- **Real HA Core check (CI, network off):**
  - a fresh install refuses to enable;
  - after commissioning, one poll produces exactly **one** captured `Manual:70`
    (never sent anywhere), with no duplicates on repeated evaluation;
  - observed Manual confirms it;
  - after a reload the master switch stays on and the controller re-inspects;
  - disabling sends nothing.

## Known limits and risks

- **T3 not yet done.** The bridge's own `Manual:70`/`Auto` have not been
  physically qualified (needs separate approval).
- **Element sensing is empirical.** The `WaterHeaterSts` bit-0 meaning is
  inferred from 5/5 transitions plus the T1 power steps, not a manufacturer
  contract. Physical confirmation uses the meter.
- **Antibacterial interaction.** Its behaviour under Manual ↔ Schedule switching
  is product-level evidence only; the controller never interrupts unexplained
  heating.
- **No real-world statistics yet.** Closed-loop results use a simple thermostat
  and tank model.
- **Cloud dependency.** The vendor cloud remains a single dependency; see
  [LOCAL_CONTROL_FEASIBILITY.md](LOCAL_CONTROL_FEASIBILITY.md).
