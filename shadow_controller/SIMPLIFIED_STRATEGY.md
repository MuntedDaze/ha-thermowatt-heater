# Simplified heating strategy: review and proposal (12 Nov 2026, revised after the owner's clarification)

**Status: proposal for owner review.** The installed controller (0.7.1) and the
bridge (1.3.11) are unchanged. This branch adds only a pure, unwired policy
module (`custom_components/thermann_shadow/simple_policy.py`) and its tests
(`tests/test_simple_policy.py`). Nothing imports the module. Using it needs the
approvals in section 9.

**Design requirement (owner, 12 Nov 2026): the baseline is Manual 45 °C.** It
applies during weekday overnight off-peak and throughout weekends, and never
in a weekday peak. The policy, tests and simulations all use 45 °C. Section 3
records an open compliance concern for review. It does not change the
requirement.

## 1. What is unnecessarily complicated today

The controller has two decision engines plus glue that reconciles them:

- **Planner** (`strategy.py`, `goals.py`, `advisor.py`, `model.py`): plans
  heating blocks against forecast slots for several goals at once.
- **Economic permission** (`permission.py`): a second, meter-priced decision
  that grants or withdraws Manual 70 °C.
- **Glue** (`control_plan.py`): the morning fail-safe, the comfort fallback, the
  holiday rules, the session temperature cap, and the rounding of each decision
  to a command slot.

Each layer has its own timers, and they stack:

| Where | Timer |
| --- | --- |
| Permission | 10-minute rolling median, 10-minute economic hold, 5-minute peak hold |
| Control plan | command slot (half the 30-minute latency reserve), 5-minute peak guard, 90-minute session settle, 4-hour morning fail-safe window |
| Controller | 30-minute minimum heating, 30-minute minimum rest, 6 commands a day (2 reserved), 65-minute confirmation timeout |
| Bridge | 20-second command interval, 60 s and 300 s confirmation reads, 60-second refresh spacing |

**The morning goals cause the most complexity for the least benefit.** They
work from the bottom-sensor reading, with a cooling allowance and an
uncertainty margin, to guarantee 45 °C at 06:00 and 42 °C at 07:00. On the
first Stage C night (12 Nov) the plan was to run Manual 70 from about 00:45 to
reach that reading, which meant heating the whole tank to 70 °C overnight. The
native thermostat at a lower target would have done the same job with no
calculation.

**The rules have gaps.** Nothing covers hot water after a big evening draw. On
12 Nov the bottom reading fell from 65 to 25 °C between 18:08 and 18:38, and
nothing would have reheated it until after midnight.

**The weekend goal forces heating.** The weekend "afternoon ready" goal heats
to 70 °C every Saturday and Sunday, whether or not there is solar to use.

## 2. Is switching between Manual 45 °C and Manual 70 °C practical?

**At the cloud API: yes.** Both transitions are a single request:

| Transition | Request |
| --- | --- |
| OFF → Manual X | POST `/manual` with `T_SetPoint: X` |
| Manual X → Manual Y | POST `/manual` with `T_SetPoint: Y` |

No intermediate mode is needed. Each transition costs the same as today's
commands: the POST, its confirmation reads (two or three), and one status
refresh if the last status is more than 60 s old.

**The heater accepts 45 °C.** At 20:38 on 12 Nov the owner selected Manual
45 °C in the app, and the cloud reported Manual with a 45 °C target. A 45 °C
target sent *by the bridge* has not been tested yet; it needs a supervised
qualification run, like T3.

**The bridge would refuse almost every transition this design needs.** The
automation policy accepts exactly `Manual:70` and `off`, and:

- it refuses `Manual:<anything else>`;
- it enters Manual only from OFF, so Manual → Manual is refused;
- it parks only from Manual 70, so `off` from Manual 45 is refused;
- it treats any target other than 70 °C as the owner's choice, and refuses the
  command (`refused_target_mismatch`).

The bridge uses "target is 70 °C" as its test for whether the controller or the
owner set the current state. With two controller targets, that test cannot tell
the controller's 45 °C from the owner's 45 °C.

**The bridge change needed** (requires approval):

- Accept exactly three states: OFF, Manual at the approved baseline, and
  Manual 70.
- Have each command state the prior state it expects, for example
  `Manual:70@45` (well under the 32-byte limit). Refuse the command when the
  fresh status (at most 60 s old) shows anything else.

This keeps the protection against overriding an owner change in the app.
Everything else stays as it is: no retries, one pending command, bounded
confirmation.

**How much hot water each target gives.** With the 8 °C hysteresis, Manual 45
reheats only when the bottom reading falls to about 37 °C. With 15 °C inlet
water, a fully mixed tank holds roughly:

| Tank | Water at 40 °C |
| --- | --- |
| 70 °C | 690 L |
| 45 °C | 380 L (about 4–5 showers) |
| 37 °C | lukewarm |

The bottom sensor reads well below the top after draws, so actual availability
is better than the reading suggests. A 45 °C baseline holds roughly half the
reserve. That is why weekday
evenings start from 70 °C.


## 3. Safety, the heater's own protections and an open compliance note

### 3.1 Native protections

The Thermann guide (p10) says the antibacterial cycle heats the water above
62 °C for 32 minutes every 7 days if that has not otherwise happened,
"regardless of the mode". OFF keeps both antibacterial and frost protection.
The heater manages these itself, so the policy has **no antibacterial
subsystem**:

- no detection;
- no exposure tracking;
- no overdue warning;
- no hold for protective heating.

It never commands anything that disables them: every state it uses (OFF,
Manual 45, Manual 70) keeps them active. The weekday 70 °C storage reaches the
cycle's temperature most weekdays anyway.

### 3.2 Open compliance note (for review; it does not change the design)

- **Tasmania.** The building regulator's guidance (CBOS, citing AS/NZS 3500.4)
  says the temperature setting for stored heated water must not be less than
  60 °C. A Manual 45 °C setting is below that wording.
- **NCC.** NCC Volume Three's verification method B2V1 (formerly BV2.2) is
  satisfied when all stored water is held at one of the following within
  7 days before it reaches an outlet:
  - 60 °C for 32 minutes;
  - 66 °C for 2 minutes;
  - 70 °C for 1 second.

  Thermann's cycle appears designed around that kind of criterion.
- **Thermann's guide** recommends a Manual minimum of 50 °C.
- **Still open:** whether a 45 °C Manual setting, with the native cycle and
  weekday 70 °C heating, is acceptable for this installation. Thermann or a
  licensed plumber (or CBOS) can confirm that; this review cannot.
- **Scald protection** at outlets (the tempering valve) is unaffected.

**Cloud limitations:**

- No API field reports the element's state or the active schedule.
- The access token lasts under 30 minutes (see section 7).

## 4. The policy

There are three heater states:

| State | Heater setting |
| --- | --- |
| **OFF** | Software OFF |
| **BASELINE** | Manual 45 °C |
| **STORAGE** | Manual 70 °C |

The tariff calendar decides which rule applies:

| When (from the Aurora 93 calendar) | Rule |
| --- | --- |
| Any peak, morning or evening, and the 2 minutes before it | **OFF**, unless measured surplus allows STORAGE (section 4.3). |
| Weekday off-peak before the evening peak | Heat to 70 °C in the **cheapest window that finishes by the soft target** (section 4.1). |
| Weekday night after the evening peak | **Manual 45 °C**. The native thermostat handles comfort, including recovery after evening showers. |
| Weekend (all off-peak) | **Manual 45 °C**, plus STORAGE when solar heating is worth it (section 4.4). There is no weekend deadline. |

### 4.1 Weekday: EMHASS chooses the cheapest window

| Target | Winter | Summer |
| --- | --- | --- |
| Soft target: 70 °C, preferred by | 15:30 | 16:30 |
| Hard boundary: evening peak starts | 16:00 | 17:00 |

**How the plan is made.** The policy recalculates every minute, locally, with
no cloud request:

1. **Heating time.** It comes from the reading and the physical heating rate
   of a 315 L tank with a 3 kW element, about 8.2 °C an hour. (The observed
   rate is not used; the thermal observer is diagnostic only.) A stale reading
   is assumed cold (37 °C), so the plan starts earlier, never later.
2. **Expected surplus, slot by slot.** The day is split into 5-minute slots up
   to the soft target:
   - for the first 30 minutes, the **measured** GoodWe surplus (actual solar
     minus actual household load, excluding the element);
   - after that, the **EMHASS** net-export forecast;
   - a slot the forecast does not cover counts as no surplus, so a missing
     forecast never makes waiting look cheaper;
   - with **no forecast at all** (0.9.1), grid-only heating is not started
     early: it waits for the latest start, measured solar can still start it
     sooner, and an alert is raised after an hour. Automatic control cannot be
     turned on without *Use published forecasts*.
3. **Cost of each window.** Each candidate window lasts the full heating time.
   Its cost per kWh of heat mixes surplus at the feed-in rate with grid import
   at the tariff rate.
4. **Choice.** It picks the earliest start that no later start beats by more
   than 0.5 c/kWh. If that is now, it starts. Otherwise it waits.
5. **Latest start.** At the latest start (soft target minus heating time) it
   starts regardless.

**Example.** At 45 °C, 3 hours of heating are needed. EMHASS forecasts strong
solar from 13:00, so the policy waits until 13:00. If the sun only arrives at
15:00, it starts at the latest start, about 13:30, on off-peak grid.

**After a big draw.** If the target can no longer be met, it heats at once and
keeps heating until the peak boundary.

**Setpoint is not achievement.** Manual 70 °C is the *requested* setpoint. The
thermostat holds the tank between about 62 and 70 °C (8 °C hysteresis), so a
reading of 65 °C is reported as "within the thermostat band", not as 70 °C
reached (`target_reached` needs a fresh reading of at least 70 °C). The
decision is unchanged: in that band no heat would flow, so the policy sends
nothing and never forces the element to cycle.

### 4.2 Once weekday heating has started

Storage normally continues until the peak. Clouds, falling surplus or higher
household imports do **not** stop it, and the thermostat stops the element at
70 °C.

It pauses only when all of these hold:

- EMHASS shows a later window that saves at least **$0.30** over the remaining
  heat;
- that window starts at least 15 minutes from now (the command spacing);
- it still finishes by the soft target.

A cloud alone can never trigger a pause. Measured surplus stands in for the
forecast for only 30 minutes, which is worth at most about $0.12 of heat.

When it is running late, it never pauses.

**The soft target is a planning buffer, not a shutdown.** Heating that has not
finished by 15:30 or 16:30 continues until the peak boundary.

### 4.3 Peaks: one rule, morning and evening

- **Start:** Manual 70 °C only after at least **3.3 kW** of measured surplus
  for **10 minutes**: the samples at the start and the end of the 10 minutes
  both pass, and at least 80 % of those between. The element's own load is
  excluded (and counted only while the heater is in Manual, never from a
  low-confidence estimate), and forecasts never count.
- **Withdraw:** after **5 minutes** (the same sample rule) in which either:
  - grid import is above **0.2 kW**; or
  - the surplus is below the element's 3 kW (less the 0.2 kW tolerance). This
    check also applies while the thermostat has the element off.

  The withdrawal OFF is the **one command exempt from the command spacing**
  (0.9.1, owner-approved): it is sent even within 15 minutes of the start.
- **Restart:** a new 10-minute qualification, and the 15-minute command
  spacing.
- **Park lead: 2 minutes.** That is one decision tick plus the bridge's
  pre-command refresh and POST (seconds), plus the measured cloud readback
  (about 2–63 s in T3c). So the park lands before the boundary without
  stopping 15 minutes early.
- **Reserved command slot:** for the 15 minutes before the park, the policy
  sends nothing except OFF. Nothing it sends can then push the park past the
  boundary through the spacing rule.

### 4.4 Weekends and weekday nights

**Manual 45 °C** is the baseline. It switches to Manual 70 °C when all of
these hold:

- at least **1 kW** of measured surplus for 10 minutes;
- the heating window now saves at least 2 c/kWh against off-peak grid;
- EMHASS shows no cheaper window later that day;
- the heating can finish before the next peak.

A session ends only when **both** of these are true:

- the measured surplus has been below 1 kW for 5 minutes;
- the next hour's forecast is below 1 kW.

So a passing cloud does not interrupt a worthwhile session.

### 4.5 Precedence and examples

**Precedence,** highest first. Layer 3 can only block a command; it never
chooses a state.

1. The heater's own protections: native, in every state.
2. Owner: an app change or hold (hold), holiday mode (OFF), 12hr Override
   (STORAGE).
3. Cloud, authentication, freshness, command spacing and the reserved park
   slot.
4. The peak import restriction.
5. Hot water before the evening peak, and the baseline.
6. Forecast economics, which can only move an off-peak start or pause for a
   clearly cheaper window.

**A typical weekday has four commands,** the same number as today:

| Time (summer) | Command |
| --- | --- |
| 07:58 | Park (OFF) |
| The cheapest window, often 11:00–14:00, or during the morning peak on measured solar | Start STORAGE |
| 16:58 | Park (OFF) |
| 22:00 | Manual 45 °C |

**A weekend day** has 0–2 commands.

**Day changes need no special case.** Friday → Saturday stays on Manual 45 °C,
and Sunday → Monday parks at 07:58.

**Invariant, tested in every simulation:** the heater is never in Manual 45 °C
during a peak minute. A separate test checks that every Manual 45 °C command
falls in an off-peak baseline period.

**Simulation results** (`tests/test_simple_policy.py`):

| Scenario | Commands | Grid heating | Peak grid heating | Outcome |
| --- | --- | --- | --- | --- |
| Summer weekday, sunny | 4 | 0 kWh | 0 | Storage started on peak solar at 09:12; 69 °C by 16:30 |
| Summer weekday, overcast | 4 | 4.0 kWh | 0 | Started at 11:00, when every window cost the same |
| Cloud until 13:00, then sun (forecast) | 4 | 0 kWh | 0 | Waited; started at 13:00; 70 °C by 16:30 |
| The same day without that forecast | 4 | 5.2 kWh | 0 | Started at 11:00: shows the forecast's value |
| Sunny forecast, cloudy day | 4 | 6.1 kWh | 0 | Waited for the promised sun; started at 14:10; 70 °C by 16:30 |
| An hour of cloud after starting | 4 | 2.6 kWh | 0 | Not paused |
| Winter weekday | 4 | 0.3 kWh | 0 | Started at 10:38; 69.5 °C by 15:30 |
| Monday 18:30 showers (68 → 25 °C) | 3 | 9.0 kWh | 0 | No peak reheat; Manual 45 °C recovered it overnight |
| Friday noon → Monday 18:00 | 7 | 0 kWh | 0 | One Sunday solar session |
| Saturday with a 15-minute cloud at noon | 2 | 0.4 kWh | 0 | One session, not interrupted |
| Cloudy weekend | 0 | – | – | Manual 45 °C only |

## 5. Is 1 kW a sensible weekend solar threshold?

**As a floor, yes. As a trigger, no.** With a 3 kW element, 1 kW of solar means
2 kW of grid. That heat costs (1 × 9.28 + 2 × 17.02) / 3 = **14.4 c/kWh**,
against 17.02 c off-peak:

| Measured surplus | Saving on off-peak | Over a 45 → 70 °C heat (9 kWh) |
| --- | --- | --- |
| 1 kW | 2.6 c/kWh | About 24 c |
| 1.5 kW | 3.9 c/kWh | About 35 c |
| 3 kW (all solar) | 7.7 c/kWh | About 70 c |

Storing at 70 °C rather than the baseline also loses roughly 0.5–1 kWh more
over the following day, worth about 8–17 c. So 1 kW is close to break-even.
That is why the weekend rule also needs a 2 c/kWh saving over the whole
window, and waits when EMHASS shows a cheaper window later.

## 6. Shared safeguards

The guide's 8 °C hysteresis governs the **element**, and the native thermostat
does that switching. The guide gives no limit on mode or target changes. So
the policy has no minimum heating, minimum rest or fallback timers.

| Safeguard | Used for |
| --- | --- |
| 10-minute solar qualification (80 % of samples) | Peak starts (3.3 kW) and weekend starts (1 kW) |
| 5-minute withdrawal | Peak: import above 0.2 kW, or surplus below the element. Weekend: surplus below 1 kW, together with a faded forecast. |
| 15-minute command spacing | Every command except the peak withdrawal OFF. One command is outstanding until confirmed. |
| 2-minute park lead and the reserved slot before it | Every peak |
| 30-minute soft target | A planning buffer before the evening peak |
| $0.30 pause threshold | The only reason to stop committed weekday heating early |
| 6 commands and 220 requests a day | Backstop only. A normal weekday uses 4 commands. Optional solar starts stop at 6; essential commands (weekday heat, Manual 45 °C, the 12hr Override) may reach 12; OFF is never held back. |
| Bridge freshness (≤ 60 s), one pending command, bounded confirmation, no retries | Unchanged |

**Dropped:**

- minimum heating and minimum rest;
- command-slot rounding;
- the session settle;
- the morning fail-safe window and cooling allowance;
- the 15-minute park lead.

## 7. Cloud traffic and polling

The 26 hours to 21:09 on 12 Nov included installs, restarts, the supervised
tests and the first Stage C command. They used 198 requests:

| Category | Requests |
| --- | --- |
| Status polls | 105 |
| Token refreshes | 48 |
| Device discovery | 17 |
| Command confirmations | 13 |
| Commands | 8 |
| Pre-command refreshes | 7 |

**Where the steady 141–147 a day comes from:** every 30-minute poll is `GET`
(401) → token refresh → `GET`. That is **3 requests per poll, or 144 a day**,
before any command. The access token lasts less than 30 minutes, and the bridge
refreshes it only after a 401.

**The policy itself adds no cloud traffic.** It evaluates the plan and the
GoodWe samples locally every minute. It needs a Thermann reading only for the
plan (one up to 75 minutes old is accepted), and the bridge's fresh read only
when it sends a command.

### 7.1 Evaluation: aligning polls to :00 and :30

**Today** (bridge 1.3.11):

- the bridge polls 30 minutes after its last background poll, so the times
  drift with every restart;
- an on-demand refresh resets that timer
  (`next_background = now + interval`), so it shifts the schedule;
- a command's own reads count as the due poll only if they happen in the same
  tick.

**Proposed for bridge 1.3.13 (needs approval):**

- **Clock-aligned polls** at :00 and :30 local time. After a restart or an
  extra read, the next poll is still the next :00 or :30, so the schedule never
  shifts.
- **Reuse.** Skip a scheduled poll if a status read, or a command's refresh
  or confirmation read, finished or is in progress within the last 5 minutes.
  The next slot stays on the grid. Never run two reads at once.
- **Guarded extra reads,** each still through the existing authentication,
  backoff, quota and accounting gates:
  - one at startup, or when control is activated;
  - the existing pre-command refresh when the status is more than 60 s old;
  - the bounded confirmation reads.

**Benefits:**

- A reading lands at the tariff boundaries and at the soft targets (15:30 and
  16:30), and EMHASS's 30-minute slots line up with the readings.
- Restarts no longer move the schedule.
- The park at 16:58 brings its own reads (refresh, then confirmations at about
  16:59 and 17:03), so the 17:00 poll is reused rather than repeated. That saves
  1–2 requests a day.

**The same 48 polls a day.** Alignment does not change the token cost: each
poll still costs 3 requests until the token is refreshed before the poll.

**Risk:** small. It changes only when the existing reads happen, not how many
are allowed or how they are guarded. A bridge release still needs the usual
mocked tests and approval.

### 7.2 Other reductions

| Change | Saving | Needs |
| --- | --- | --- |
| Refresh the token *before* the poll when it is known to have expired | 48 a day (−33 %) | Owner approval: an authentication change, the same area as PR #3 |
| Drop the immediate confirmation read. It showed the old mode in T3b and T3c, and the 60-second read confirmed. | 1 per command (about 4 a day) | Owner approval: command confirmation |
| Clock-aligned polling with reuse | 1–2 a day | Bridge 1.3.13 (section 7.1) |
| Fewer weekend commands (0–2 a day, against 2–4 with the afternoon goal) | 2–8 a weekend | This policy |

**Realistic result:** about 100 requests a day with the token and confirmation
changes, at the same 30-minute polling. Without the authentication change,
about 140.

## 8. What stays unchanged

**Bridge:**

- authentication guard, lockouts and backoff;
- request accounting;
- command freshness;
- one pending command, bounded confirmation, and never retrying a refused or
  unconfirmed command;
- an exact command allowlist (extended to three states with a stated prior
  state);
- 30-minute polling (aligned to :00 and :30 if 1.3.13 is approved).

**Controller:**

- the state-machine shell: disabled, observing, confirming, owner override and
  fault locked;
- owner app-change detection and resume;
- holiday mode and the 12hr Override;
- fault handling and notifications;
- the daily command and request budgets;
- entity IDs, and the settings locked while control is active.

**Elsewhere:**

- the read-only thermal observer;
- OFF as the park state; the heater keeps its own protections in every state.


## 9. Next steps, each needing owner approval

**Implementation status:** items 2 and 3 are implemented and tested offline, as
draft PRs:

- app 1.3.13 (#25): three-state commands and clock-aligned polling, plus
  proactive token refresh and no immediate confirmation read from item 4;
- controller 0.9.0 (#26): this policy wired in, the planner removed, and shadow
  observation.

The deployment, supervised tests and rollback are in
[COMMISSIONING_SIMPLIFIED.md](COMMISSIONING_SIMPLIFIED.md). Nothing is
installed.


1. **Compliance confirmation** (section 3.2), at the owner's discretion. The
   design stays at Manual 45 °C.
2. **Bridge 1.3.13:**
   - guarded commands for exactly OFF, `Manual:45` and `Manual:70`, each
     stating its prior state;
   - clock-aligned polling with reuse (section 7.1);
   - a supervised qualification of `Manual:45` from OFF, of 45 ↔ 70 target
     changes, and of `off` from Manual 45.
3. **Controller:** run `simple_policy` in shadow first, as a read-only
   "would do" sensor alongside the live controller, fed by the existing EMHASS
   forecast and GoodWe samples. Then wire it into the executor and delete the
   planner, goals, permission and morning fail-safe code and their settings.
4. **Optional traffic changes:**
   - token pre-refresh;
   - dropping the immediate confirmation read.

Sources: [CBOS heated water](https://cbos.tas.gov.au/topics/technical-regulation/plumbing-standards/heated-water),
[NCC 2022 Volume Three, Part B2](https://ncc.abcb.gov.au/editions/ncc-2022/adopted/volume-three/b-water-services/part-b2-heated-water-services),
[Thermann owner's guide](https://www.thermann.com.au/thermann-cms/files/Thermann-Smart_Electric-Owners_Guide.pdf)
and the [installer's manual](https://digitalassets.reecegroup.com.au/m/65539137e892f4b1/original/Installer-s-Manual-Thermann-Smart-Electric-Water-Heaters.pdf)
(paraphrased in `docs/history/controller/STAGE_4A_CONTROL_METHOD.md`).
