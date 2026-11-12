# Simplified heating strategy: review and proposal (12 Nov 2026)

**Status: proposal for owner review.** The installed controller (0.7.1) and the
bridge (1.3.11) are unchanged. This branch adds only a pure, unwired policy
module (`custom_components/thermann_shadow/simple_policy.py`) and its tests
(`tests/test_simple_policy.py`). Nothing imports the module. Using it needs the
owner's decisions in section 3 and the approvals in section 9.

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
is better than the reading suggests. Even so, a 45 °C baseline roughly halves
the reserve.

## 3. Safety, compliance and cloud limitations (unresolved: owner decision)

**Tasmania.** The building regulator's guidance (CBOS, citing AS/NZS 3500.4)
says the *temperature setting* for stored heated water must not be less than
60 °C, to control Legionella. A Manual 45 °C target (or 50 °C) is below that
setting, so a 45 °C baseline does **not** follow the stated rule.

**NCC Volume Three.** The verification method B2V1 (formerly BV2.2) is
satisfied when all stored water is held at one of the following within 7 days
before it reaches an outlet:

- 60 °C for 32 minutes;
- 66 °C for 2 minutes;
- 70 °C for 1 second.

**Thermann.** The owner's guide gives a recommended Manual minimum of 50 °C. It
describes an antibacterial cycle that heats the water above 62 °C for
32 minutes every 7 days if that has not otherwise happened, "regardless of the
mode", and blocks app setting changes while it runs.

**What follows:**

- The antibacterial cycle looks designed for the 7-day criterion. Whether a
  45 °C setting relying on it is acceptable for this installation is for
  Thermann and a licensed plumber (or CBOS) to confirm. This review cannot
  certify it.
- The proposed weekday plan heats to 62–70 °C (bottom reading) every weekday.
  That reaches the exposure temperatures far more often than every 7 days. The
  longest routine gap is a weekend, about 3 days.
- The antibacterial cycle remains the backstop for holidays, outages and missed
  targets.
- No controller-scheduled hygiene heating is proposed. The controller must
  never block, interrupt or misread the manufacturer's cycle (precedence
  layer 1).
- A command sent while the cycle is running may be refused, or may not take
  effect. The bridge records it as not confirmed and never retries it.
- Scald protection at outlets (the tempering valve) is unaffected.

**Options for the baseline.** It is a single setting, and the design is the
same for any value:

| Baseline | Tasmanian 60 °C setting | Manufacturer 50 °C minimum | Notes |
| --- | --- | --- | --- |
| **60 °C** | Meets it | Meets it | Reheats at about 52 °C, overnight only after draws; most comfort; recommended |
| 50 °C | Below it | At the minimum | Reheats at about 42 °C |
| 45 °C | Below it | Below it | Reheats at about 37 °C; owner's proposal; needs Thermann/plumber confirmation first |

**Recommendation: start at 60 °C.** The cost difference is small. Extra
overnight heating happens only after large draws, at 17 c, and most of that
heat would be bought the next day anyway. On sunny days some of it would
otherwise have come from solar at 9 c, a difference of up to about 40 c on a
day after heavy use.

**Cloud limitations:**

- No API field reports the antibacterial cycle, the element's state or the
  active schedule. The controller infers protective heating, for example
  heating while OFF or a rise above the target.
- Token lifetime is under 30 minutes (see section 7).

## 4. The simplest coordinated policy

There are three heater states, and the tariff calendar decides which applies:

| State | Heater setting |
| --- | --- |
| **OFF** | Software OFF (antibacterial and frost protection stay active) |
| **BASELINE** | Manual at the baseline target |
| **STORAGE** | Manual at 70 °C |

| When (from the Aurora 93 calendar) | State |
| --- | --- |
| Weekday peak, and the 15 minutes before one | **OFF**. STORAGE only while *measured* surplus has been at least 3.3 kW for 10 minutes. Withdraw after 5 minutes of grid import above 0.2 kW. Forecasts never qualify. |
| Weekday daytime before the evening peak (from 09:00, or the end of the morning peak) | Stay as you are (no command), then **STORAGE until the peak**. See below for when storage starts. |
| Weekday night after the evening peak | **BASELINE**. The native thermostat handles comfort, including recovery after evening showers. |
| Weekend (all off-peak) | **BASELINE**, plus STORAGE while solar heating is worth it (section 5) and can finish before the next peak |

Storage starts at the **latest start** that still finishes 30 minutes before
the peak. The heating time comes from the reading and the observed heating
rate, and a stale reading is assumed cold. It starts **earlier** when any of
these holds:

- measured solar of at least 1 kW is no dearer than the best forecast hour
  before the latest start;
- no solar is forecast before then (start on off-peak at once);
- the tank is at or below the baseline's reheat point.

Once started on a weekday, storage runs until the peak. Stopping and
restarting later at the same off-peak price would only add commands. A target
that cannot be met is reported, and the heater still parks for the peak.

**A typical weekday** has four commands, the same number as today:

| Time | Command |
| --- | --- |
| 07:45 | Park (OFF) |
| About 11:00–14:00 | Start STORAGE (or during the morning peak, on measured solar) |
| 16:45 | Park (OFF) |
| 22:00 | BASELINE |

**A weekend day** has 0–2 commands.

**Day changes need no special case.** The calendar handles Friday → Saturday
(BASELINE carries on) and Sunday → Monday (park at 07:45 for Monday's 08:00
peak).

**Precedence,** highest first. Layer 3 can only block a command; it never
chooses a state.

1. Manufacturer protective heating (antibacterial, frost): hold, never a command.
2. Owner: an app change or hold (hold), holiday mode (OFF), 12hr Override (STORAGE).
3. Cloud, authentication, freshness and command spacing.
4. The weekday peak import restriction.
5. Hot-water comfort and economical heating.
6. Forecast optimisation, which can only move an off-peak start earlier or later.

**Simulation results** (`tests/test_simple_policy.py`):

| Scenario | Commands | Grid heating | Peak grid heating | Outcome |
| --- | --- | --- | --- | --- |
| Summer weekday, sunny | 4 | 0 kWh | 0 | Storage started on peak solar at 09:12 |
| Summer weekday, overcast | 4 | 4.0 kWh | 0 | Started at 11:00 |
| Sunny forecast, cloudy day | 4 | 6.2 kWh | 0 | Started at the latest start, 14:19; reached 70 °C by 16:44 |
| Winter weekday | 4 | 0.1 kWh | 0 | Target met before 16:00 |
| Monday 18:30 showers (68 → 25 °C) | 3 | 9.0 kWh | 0 | No peak reheat; BASELINE at 22:00 recovered it overnight; no 70 °C overnight |
| Friday noon → Monday 18:00 | 7 | 0 kWh | 0 | Weekend solar opportunity on Sunday |
| Cloudy weekend | 0 | – | – | BASELINE only |

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
The policy therefore starts weekend storage only when all of these hold:

- at least 1 kW has been measured for 10 minutes;
- no better hour is forecast later today ("wait for the 3–4 kW at noon");
- it saves at least 2 c/kWh against off-peak grid power (heat that is not
  otherwise needed);
- the heating can finish before the next peak.

Weekend storage ends after 5 minutes below 0.5 kW. On a cloudy weekend nothing
forces 70 °C.

## 6. Which delays and safeguards are needed

**Manufacturer switching guidance:**

- The guide's 8 °C hysteresis governs the **element**. The native thermostat
  does that switching. It micro-cycled 4 times in 8 minutes near cut-off on
  10 Nov, without any command.
- The guide gives no limit on **mode or target changes** or on **cloud
  commands**.
- So the 30-minute minimum heating and 30-minute minimum rest have no
  manufacturer basis. Neither are they needed for stability once one
  qualification rule and one withdrawal rule exist.

| Safeguard | Keep? | Why |
| --- | --- | --- |
| 10-minute solar qualification (80 % of samples) | Keep: one rule, used for peak and off-peak | Passing clouds and kettles |
| 5-minute import withdrawal (above 0.2 kW in a peak) | Keep | Owner's rule. The element's own load is excluded, so starting the element does not look like lost solar. |
| 15-minute minimum between commands | Keep: one rule | One command is outstanding until confirmed (up to about 6 minutes), and the next decision should use the confirmed state. This limit is ours, not the manufacturer's. |
| 15-minute park lead before a peak | Keep. It equals the spacing. | A command just before the lead window can then never push the peak OFF into the peak. |
| 30-minute finish margin | Keep | Covers a late start and the uncertainty in the heating rate |
| Minimum heating / minimum rest | **Drop** | No basis (see above); covered by qualification, withdrawal and spacing |
| Command slot rounding, session settle, morning fail-safe window and cooling allowance | **Drop** | Replaced by the native thermostat and the latest-start rule |
| 6 commands a day, 220 requests a day | Keep, as a backstop only | Bugs. A normal weekday uses 4. |
| Bridge freshness (≤ 60 s), one pending command, bounded confirmation, no retries | Keep unchanged | Cloud safety |

## 7. How much cloud traffic can be reduced

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
refreshes it only after a 401. Discovery happens only after a restart or an
MQTT reconnect.

| Change | Saving | Needs |
| --- | --- | --- |
| Refresh the token *before* the poll when it is known to have expired | 48 a day (−33 %) | Owner approval: an authentication change, the same area as PR #3 |
| Drop the immediate confirmation read. It showed the old mode in T3b and in Stage C, and the 60-second read confirmed. | 1 per command (about 4 a day) | Owner approval: command confirmation |
| Weekend commands (0–2 a day, against 2–4 with the afternoon goal) | 2–8 a weekend | This policy |
| Never command a state that is already active | Already done by both the policy and the bridge | – |

**Realistic result:** about 100 requests a day with the first two changes, at
the same 30-minute polling. Without the authentication change, about 140.

**Switching between Manual 45 and Manual 70 adds no traffic,** because the
number of commands stays at four a weekday.

**On-demand refresh:** the bridge already has a guarded one (MQTT
`P/<serial>/refresh`). It is limited to one read per 5 minutes, it reuses a
recent poll, and it honours the cloud health, authentication and accounting
gates. It is **disabled** on the live bridge (`on_demand_refresh_enabled:
false`), and the controller never requests it. Using it once when automatic
control is enabled, after a restart and after a recovery would cost about 3
requests each time. In return, the first decision would not wait up to
30 minutes: Stage C waited 26 minutes on 12 Nov. This needs a bridge option
change and a small controller change, both with approval.

## 8. What stays unchanged

**Bridge:**

- authentication guard, lockouts and backoff;
- request accounting;
- command freshness;
- one pending command, bounded confirmation, and never retrying a refused or
  unconfirmed command;
- an exact command allowlist (extended to three states with a stated prior
  state);
- 30-minute polling.

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
- OFF as the park state, which keeps the manufacturer's protections.

## 9. Next steps, each needing owner approval

1. **Choose the baseline:** 60 °C is recommended. 45 °C should wait for
   Thermann and plumber confirmation.
2. **Bridge 1.3.13:** three-state guarded commands with a stated prior state,
   then a supervised qualification of Manual:<baseline> and of Manual → Manual
   target changes.
3. **Controller:** run `simple_policy` in shadow first, as a read-only
   "would do" sensor alongside the live controller. Then wire it into the
   executor and delete the planner, goals, permission and morning fail-safe
   code and their settings.
4. **Optional traffic changes:** token pre-refresh, dropping the immediate
   confirmation read, and on-demand refresh when control is enabled or after a
   restart or recovery.

Sources: [CBOS heated water](https://cbos.tas.gov.au/topics/technical-regulation/plumbing-standards/heated-water),
[NCC 2022 Volume Three, Part B2](https://ncc.abcb.gov.au/editions/ncc-2022/adopted/volume-three/b-water-services/part-b2-heated-water-services),
[Thermann owner's guide](https://www.thermann.com.au/thermann-cms/files/Thermann-Smart_Electric-Owners_Guide.pdf)
and the [installer's manual](https://digitalassets.reecegroup.com.au/m/65539137e892f4b1/original/Installer-s-Manual-Thermann-Smart-Electric-Water-Heaters.pdf)
(paraphrased in `docs/history/controller/STAGE_4A_CONTROL_METHOD.md`).
