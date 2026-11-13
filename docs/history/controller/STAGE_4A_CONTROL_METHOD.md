# Stage 4A — Thermann control method: investigation and supervised validation plan

**Status: decided (owner, 11 Nov 2026).** Manual 70 °C = heating permitted;
**empty weekly Schedule** = normal heating parked. T1 passed in the official
app; T2 (Off/On) is **optional** and not a prerequisite; T3 (bridge commands) is
the next physical gate. Apart from the owner's own app test, no heater command,
option change, Schedule or T-Comfort edit, extra Thermann request or deployment
was made. Thermowatt add-on 1.3.8 is unchanged and still
has `commands_enabled: false` and `on_demand_refresh_enabled: false`.

The owner accepts manual recovery if Home Assistant or the cloud fails, so a fully
automatic fallback is not a prerequisite. Manufacturer safety stays first.

## Revision (owner, 12 Nov 2026) — parked state changed to software OFF

App testing found that a completely **empty** native Schedule made the app's
setpoint revert to 40 °C after it was reopened. Manual 70 °C and app OFF/ON both
kept 70 °C. The owner's guide confirms OFF keeps antibacterial and frost
protection while mains stays connected.

**Final method:** Manual 70 °C = heating permitted; Thermann software **OFF** =
parked. The empty-Schedule park described below is **superseded**, and no native
Schedule configuration is required.

The bridge's OFF behaviour (`off` and `Manual:70` from OFF) is qualified in T3;
see [COMMISSIONING.md](COMMISSIONING_0_6.md). Bridge 1.3.9 is required, because 1.3.8
rejects an OFF status whose setpoint is outside 20–75 °C.

## 0. Owner decision (11 Nov 2026)

- HA should control normal heating completely. The Thermann thermostat and all
  manufacturer protections stay active.
- Occasional cold showers are acceptable if HA or the cloud fails. **No automatic
  morning backup and no 13:00–16:00 backstop window** are wanted.
- **Preferred if T1 passes:** Manual 70 °C = heating permitted; an **empty native
  Schedule** (Option 2) = ordinary heating parked.
- **Use instead** if genuine software Off/On proves more reliable and can be
  controlled programmatically in both directions (Option 1).
- The owner is not attached to either method: choose the simplest, safest and
  most reliable.
- Keep investigating local-only control, but not as a prerequisite.
- **Approved:** T0–T2 only. The owner operates the official app; there are no API
  writes and no bridge option changes.
- **Not approved:** Schedule edits, an executor, or T3–T6. Each needs separate
  approval.

T1 tested the Schedule park **without editing the Schedule**: it ran outside
the existing windows, where Schedule already parks the element (the 11 Nov
00:00–04:00 evidence). Saving the empty programme is commissioning Stage C,
approved separately.

## 0a. T1 result (owner, official app, 11 Nov 2026) — PASSED

**Final architecture (owner, 11 Nov):**
- Manual 70 °C = heating permitted.
- **Empty weekly Schedule** = parked. The owner has confirmed that a blank
  Schedule works.
- No automatic fallback windows, and no `/off`. T2 is optional.
- The next physical gate is T3: proving that the bridge's own `Manual`/`Auto`
  requests reproduce the app's results. It needs separate approval.

Initial conditions: Schedule mode, target 70 °C, about 55 °C reported, the
existing windows (weekdays 04–08 and 11–17, weekends 06–22), T-Comfort 10 °C,
bridge commands disabled. The test ran during the evening peak, outside every
native window.

Recorder correlation (GoodWe HK1000 meter; negative = import):

| Time (AEDT) | Grid | Step | Owner action / app |
| --- | --- | --- | --- |
| 20:36:25 | −0.87 → −3.93 kW | +3.07 kW | Manual selected; app showed Manual 70 °C with the heating indicator on |
| 20:39:05 | −4.01 → −0.92 kW | −3.09 kW | Schedule selected; app showed Schedule with 70 °C unchanged |
| 20:41:25 | −0.91 → −3.92 kW | +3.01 kW | Manual again |
| 20:42:29 | −3.96 → −0.90 kW | −3.06 kW | Schedule again |

- **Response time.** Each mode change moved the element within one 1-minute
  meter sample. The steps match the 3 kW element in both directions.
- **Park works without the programme.** Schedule parked the element outside its
  windows with the programme unchanged.
- **Polls did not see Manual.** The bridge polls at 20:17:54 and 20:47:57 both
  saw Schedule (`Cmd` 17, 70 °C). The 6-minute test fell between them, as
  expected with 30-minute polling. There were no command or confirmation
  requests.

**Temperature 55 → 62 °C (the app showed 63 °C).** The element ran for only
about 3.7 min, about 0.19 kWh, which is roughly 0.5 °C for a uniformly mixed
315 L tank. A 7 °C rise therefore cannot be tank energy.
- It is most likely local heating at the bottom sensor, which sits beside the
  element (stratification / sensor placement), seen at the next poll 5 minutes
  after the element stopped.
- It is not a delayed reading. The 20:17 poll still showed 55 °C, falling about
  1 °C per 30 min.
- Contrast with long heating: on the morning of 11 Nov, 4 h at 3 kW (about
  12 kWh) moved the reading 16 → 49 °C. That matches the uniform-tank figure of
  about 0.37 kWh per °C.

**Consequence for control:**
- After short heating, the bottom reading overstates stored energy.
- It can also exceed the 62 °C restart point, so the thermostat may not call for
  heat again until the hot zone mixes.

The production controller therefore caps the planning temperature during and
after a session at start reading + delivered energy ÷ 0.366 kWh/°C. It plans
in heating periods of at least 30 minutes and never toggles modes to beat
hysteresis.

## 1. Final method

Use **Manual 70 °C as the "heating permitted" state** and **Schedule with an
empty weekly programme as the "parked" state**. There are no fallback heating
windows (morning or afternoon) and no `/off`.

- Both directions exist in the bridge: `/manual` carries the 70 °C target and
  `/auto` selects Schedule; readback distinguishes them (`Cmd` 9 / 17). Bridge
  1.3.9 (PR #12) adds the guarded `Manual:70` so Manual can never be entered at
  another target.
- History and T1 both show Schedule outside its windows holds the element off.
  With the programme empty, Schedule parks ordinary heating at all times; the
  antibacterial and frost functions stay with the manufacturer.
- If HA, the cloud or the bridge fails while parked, ordinary heating stays off
  until the owner selects Manual (or restores the old programme) in the app. The
  owner accepts this. If it fails in Manual, the heater behaves as a
  conventional 70 °C heater.

**Off/On (Option 1)** is structurally the same pair of writes (`Cmd` 9 ↔ 16),
but its resume path and what `Off` reports are unverified, and a stuck Off gives
no heat at all. It remains an **optional** alternative (T2), not a prerequisite.

## 2. Evidence

### 2.1 Manufacturer guide (Thermann Installer's Manual & Owner's Guide)

[PDF](https://digitalassets.reecegroup.com.au/m/65539137e892f4b1/original/Installer-s-Manual-Thermann-Smart-Electric-Water-Heaters.pdf). The guide is paraphrased here; page numbers are the printed ones.

| Topic | Guide says | Consequence |
| --- | --- | --- |
| Thermostat (p9) | Bottom sensor; reheats only once the water is **≥8 °C below** the setpoint; reading drops 2–3 °C after a cycle | "Heat permitted" ≠ heating. At 70 °C nothing starts above about 62 °C |
| Manual (p9) | Default 65 °C, 50–70 °C. A new default is saved only by Manual → Eco → Manual | Always send the target explicitly (the bridge does); never use Eco |
| Schedule (p10, p16) | Heats only during the set times; **"won't heat if a schedule is not set"**; changes must be saved | Schedule outside a window is a native park |
| T-Comfort (p17) | Schedule only. Heats to the minimum outside the windows when the reading falls ≥8 °C below it; 10 °C minimises interference; no effect in Off/Holiday | At 10 °C it never acts (frost protection covers below 5 °C). Keep it at 10 °C |
| Turn On/Off (p10) | App power button while mains is connected; **antibacterial stays active**; turned on with the same button | Product-level, not an API contract |
| Antibacterial (p10) | >62 °C for 32 min every 7 days if not otherwise reached; **"regardless of the mode"**; may run after power restore | Never suppress it or interrupt unexplained heating |
| Frost (p17) | Below 5 °C heats to 16 °C, also in Off/Holiday | Retained by every option |
| Power loss (p10) | Mains off/on does not change saved settings; power-cycling enters 5-min Wi-Fi pairing | Not a reset. No factory-reset procedure exists |
| Wi-Fi loss (p21) | A phone hotspot can stand in for the home Wi-Fi to change settings | Owner recovery route for a router failure only, not for a vendor-cloud outage |
| LEDs (p6) | Red LED = element on/off | Independent physical confirmation during supervised tests |

### 2.2 Observed behaviour (private HA history copy, 10–11 Nov; local time AEDT)

- **Window gating.** On 11 Nov the element started at 04:00 and 11:00 within about a
  minute of each window opening. It stopped at **08:00**, when the morning window
  closed, while still heating. The heater clock follows local time.
- **Park outside windows.** From 00:00 to 04:00 on 11 Nov the reading was 16 °C and
  the element stayed off. Schedule outside its windows with T-Comfort 10 °C
  therefore holds the element off, even with a nearly cold tank.
- **Hysteresis.** On 10 Nov, inside the 11:00–17:00 window, heating restarted at
  15:56 on a **62 °C** reading (70 − 8). It finished at about 16:46, with the bottom
  reading at 63–65 °C.
- **Native relay chatter.** Around the 16:46 cut-off the element switched on and off
  4 times within 8 minutes. Two or four commanded transitions a day are small by
  comparison.
  On 11 Nov the element made about 10 short bursts between 15:05 and 16:50
  before the 17:00 window end.
- **Energy.** 315 L tank, so 1 °C ≈ 0.37 kWh. A reheat from 62 to 70 °C is about
  2.9 kWh; from 45 to 70 °C about 9.2 kWh. The 3 kW element raised the reading by
  about 1 °C every 3.5–4 minutes.

### 2.3 Bridge 1.3.8 command contract (source, `thermowatt_bridge.py`)

| Gate or behaviour | Detail |
| --- | --- |
| Permission | `commands_enabled` (off). MQTT topic `P/<serial>/CMD/MODE` or `/TEMP`, non-retained, ≤32 bytes |
| Freshness | Command ≤30 s old **and** a confirmed status ≤60 s old, otherwise silently dropped (`process_command`) |
| Mode map | `Manual` → POST `/manual` with the **last observed** `T_SetPoint`; `Auto` → `/auto`; `off` → `/off`; `Eco` → `/eco`. Holiday is refused |
| Target | TEMP only while already Manual; 20–75 °C; not used by this proposal |
| Confirmation | One immediate `/status` read, then compare `Cmd`. No retry. A mismatch only logs a warning |
| Authentication | GET 401 → one token refresh + replay. **POST 401/403/429 → persistent auth block** (owner must bump `auth_retry_generation`) |
| Status validation | `T_SetPoint` outside 20–75 °C fails the poll, and the bridge backs off |
| HA entity | `water_heater` modes are only off/eco/performance. Schedule (`Cmd` 17) shows as *unknown*. `Auto` must be published as raw MQTT; HA's `turn_on` does nothing here |

**Measured request rate** (10 Nov 14:34 → 11 Nov 12:22): 134 attempts, about
6.2 per hour. That was status 86, token refresh 44, discovery 4, command 0.
Every 30-minute poll was GET 401 → refresh → GET, so the access token lasts
**under 30 minutes**.

**Poll-aligned writes** follow from that. The bridge ticks every 20 s and
processes queued commands before its own polls. A command published within
about 10 s of a background poll's STATUS update therefore meets both freshness
gates, uses a freshly refreshed token, and costs **2 requests** (POST +
confirmation). It needs **no on-demand refresh**, so that option can stay
disabled. An on-demand pre-read would cost 5 requests (GET 401, refresh, GET,
POST, GET) and needs a separate option change. The trade-off is up to 30 minutes
of command latency, which suits 15-minute planning slots and a 30-minute
minimum cycle.

## 3. Options compared

| | **1. Off/On, stay Manual 70** (optional) | **2. Manual ↔ Schedule, empty Schedule (CHOSEN)** | 3. Manual ↔ Schedule, backstop window (**declined by owner**) | 0. Today's Schedule + Manual boost |
| --- | --- | --- | --- | --- |
| Writes per heating opportunity | 2 (`/manual`, `/off`) | 2 (`/manual`, `/auto`) | 0–2 (none when the backstop alone suffices) | 1–2, but cannot stop native windows |
| Both directions exist in 1.3.8 | `/off` yes. Resume via `/manual` **unverified** (the app uses a power button) | Yes | Yes | Yes |
| Readback distinguishes states | 9 / 16. What `Off` reports for `T_SetPoint` is unknown (outside 20–75 °C would break polling) | 9 / 17 | 9 / 17 | — |
| Target retention | Explicit 70 on every `/manual`, only if the observed target stayed 70 in Off | Explicit 70; the Schedule target is also 70 | Same | — |
| Park proven to hold the element off | Product-level only | **Observed** (11 Nov, 4 h at 16 °C) | **Observed** | n/a |
| Mid-heat stop proven | No | Window-end stop observed; mode-switch stop to verify (T1) | Same | No |
| Thermostat, cut-outs, PTR valve | Unchanged | Unchanged | Unchanged | Unchanged |
| Antibacterial / frost | Stay active (guide) | Stay active | Stay active | Stay active |
| T-Comfort | No effect in Off | 10 °C, inert | 10 °C, inert | 10 °C |
| HA fails while parked | **No normal heat** until the owner presses On | No normal heat until the owner selects Manual or restores the programme | **Backstop heats before the evening peak automatically**; mornings may be cool | Native programme continues |
| HA fails in Manual | Conventional 70 °C (always hot; may reheat in peak) | Same | Same | Same |
| Cloud outage | App unusable too; heater keeps its last state (local behaviour to confirm with Thermann) | Same | Same; backstop runs from the heater's own clock | Same |
| Native programme edit by owner | None | Clear all windows | Shorten to the backstop (record the original to restore) | None |
| Economics with HA working | Full control | Full control | Full control, except that the backstop heats if the tank is still ≤62 °C at 13:00, i.e. only when HA has not already heated it | Loses the main saving: the 04:00 off-peak reheat cannot be stopped |

**Why Option 2:** it is the owner's choice and the simplest reliable method.
Both mode writes exist and were reproduced in the app (T1); the park state is
observed to hold the element off. Option 3's backstop window was proposed
earlier and **declined**: the owner prefers complete HA control and accepts
manual recovery after a failure. Option 1 stays optional.

**Rejected:**
- A low Manual target as a "stop": it is a hygiene and safety change and is not approved.
- T-Comfort as the controller: it interferes with Schedule and heats at any tariff.
- Eco: it chooses its own times and setpoints.
- Holiday: the bridge refuses it rather than invent dates.
- Rapid mode toggling, or any invented On/boost endpoint.

### Economic scale (illustrative, not a forecast)

Solar heat costs the foregone feed-in, $0.0928/kWh, against off-peak at
$0.1702/kWh and peak at $0.3619/kWh.

- **Main saving:** moving a typical 7 kWh weekday morning reheat from off-peak to
  solar saves about $0.54 on a fully sunny day.
- **Peak avoided:** keeping a 2.9 kWh peak-time reheat out of the evening peak saves
  about $0.55 more.

Annual value depends on how many days give about 3 kW of surplus for 2–3 hours.
Quantify it from at least a month of 0.4.0 shadow data (*benefit of heating now*
and the native-versus-cheapest comparison) before enabling execution.

## 4. Control policy (implemented in the 0.5.0 controller, PR #13)

1. **States.** `PARKED` = Schedule (`Cmd` 17) with the empty programme.
   `PERMITTED` = Manual (`Cmd` 9) at 70 °C. Any other observed mode or target means
   **owner control**: no automatic writes until the owner hands back.
2. **Start** when the 0.4.0 planner's stabilised decision is `heat_now_cheapest` or
   `heat_now_comfort_fallback` and the reading is ≤62 °C (otherwise the thermostat
   will not start). The pre-read must show `Cmd` 17 and `T_SetPoint` 70.
3. **Stop** by returning to Schedule:
   - when the thermostat is satisfied (the element turns off in Manual), or
   - when the planned energy is delivered (morning goal), or
   - at the **last poll before a peak**,
   - **never** while unexplained element activity could be antibacterial.
4. **Limits:**
   - writes only aligned with background polls, at most one per poll (≥30 min apart);
   - ≤6 per day (the last 2 reserved for a comfort start and its park) and ≤2 per opportunity;
   - no retries, and never the same intent twice;
   - after any unconfirmed result, stop automatic writes until the owner acknowledges.
5. **Confirmation:**
   - the bridge's immediate read, then the next poll;
   - physical confirmation from the 1-minute house meter: about +3 kW within two
     minutes of a permitted start at ≤62 °C, and about −3 kW at a stop.

   The vendor status alone is not physical proof.
6. **Recovery.** In every failure, stop automatic writes, keep the last confirmed
   state and alert the owner. The owner's manual route is the official app: select
   Manual (hot water now) or Schedule, or restore the recorded programme. An auth
   block is cleared only by the owner's documented generation bump.

## 5. Supervised validation procedure

Every step needs the owner's explicit approval at the time, the owner present,
and the official app working. Each step starts from and returns to a recorded
baseline: mode, target 70, T-Comfort 10, screenshots of all native windows.

General rules for every step:
- run in an off-peak period outside every native window (for example 22:15–23:45
  local) with the reading ≤60 °C, so the thermostat will call for heat;
- observe through the normal 30-minute polls and the house meter;
- abort by returning to the baseline in the app, and simply record unexpected
  heating, since the thermostat ends it.

Owner conditions (11 Nov) for T1/T2:
- Keep the Schedule, 70 °C target, T-Comfort and safety settings unchanged.
- Restore the original settings and confirm normal operation after each test.
- Never interrupt apparent antibacterial or protective heating: if the element is
  already on outside a window before a step, do not start.
- Stop at anything unexpected and restore.

Test-specific stop points:
- If Manual shows a target other than 70 °C, **do not adjust it**: return to
  Schedule and stop.
- If Off makes the bridge's polls fail (for example a reported target outside
  20–75 °C), the bridge backs off for 60 minutes or more. That is not an auth
  lock. The owner presses On in the app and the bridge recovers by itself.

Act straight after a background poll, so the next poll (30 minutes later) records
each state.

| Step | Who acts | Procedure | Pass criteria |
| --- | --- | --- | --- |
| **T0** Preparation | Owner (no heater action) | Record firmware 07.00.09.06, baseline screenshots, tariff, bridge options (commands/on-demand off), current request counts | Baseline recorded; restoration steps written down |
| **T1** Manual ↔ Schedule, app only (Options 2/3) | Owner in the app | From Schedule (parked), select Manual and check 70 °C. Wait ≥1 poll. Select Schedule. Wait ≥1 poll | Start ≤2 min (meter +3 kW, red LED on). Poll shows 9/70 with bit 0 set. **Stop ≤2 min after selecting Schedule**. Poll shows 17/70. Windows and T-Comfort unchanged |
| **T2** Off/On, app only (Option 1; **optional**) | Owner in the app | From Manual 70 while heating, press power Off. Wait ≥1 poll (bridge must stay healthy). Press On. Wait ≥1 poll. Return to baseline | Element stops. Record exactly what `Cmd`/`T_SetPoint` Off reports. On returns to **Manual 70** (`Cmd` 9) and heating resumes at ≤62 °C. No `status_temperature_out_of_range` |
| **T3** API equivalence | Owner sets `commands_enabled: true` for the session only | One write per poll, published right after the STATUS update: MODE `Manual:70` (bridge 1.3.9), then `Auto`. At most 4 writes; no retry. Set `commands_enabled: false` afterwards | Each write is confirmed by the immediate or next poll and by the meter, exactly as in T1/T2. Request counts rise by 2 per write. No auth block |
| **T4** Empty programme (commissioning Stage C) | Owner, in the app | Screenshot every day's windows (restore copy), then save an empty programme for every day; keep T-Comfort 10 and 70 °C | In Schedule, a former window time passes with no 3 kW step |
| **T5** Supervised trial (commissioning Stage D) | Controller 0.5.0 (PR #13), separately approved | Days with commands enabled under the §4 limits; daily review of writes, confirmations, readiness and cost | Readiness goals met; ≤6 writes/day; zero unconfirmed writes; requests within plan |
| **T6** Failure drills | Owner | HA stopped while parked or in Manual; bridge restart between start and stop | Behaviour matches §3. The owner recovers using the app |

T1 (done) and T2 (optional) involve **no API writes**. They show what the
official app does, which is the reference behaviour. T3 then checks that the
bridge's existing endpoints do the same.

Optional observation if it happens naturally: whether switching to Manual between
63 and 69 °C starts heating, i.e. whether a mode change resets the 8 °C latch.
Never force this.

## 6. Questions for Thermann (none sent)

1. Does the heater run its Schedule and thermostat locally when the cloud is unreachable?
2. What does the API `/off` correspond to in the app, and what is the supported resume?
3. Does a mode change reset the reheat hysteresis?
4. Is switching mode during an antibacterial cycle safe, and does the cycle continue?
5. Is there a recommended maximum mode-change frequency or API write rate?

## 7. Decisions (resolved, 11 Nov 2026)

1. Method: **Manual 70 °C permit / empty Schedule park** (Option 2).
2. **No** backstop or morning fallback windows; manual recovery after a failure
   is accepted.
3. T0 and T1 done (T1 passed). **T2 optional.** T3 onward are separately
   approved commissioning stages (see `COMMISSIONING.md` in PR #13).
