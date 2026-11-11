# Stage 4A — Thermann control method: investigation and supervised validation plan

**Status: proposal for ChatGPT/owner review. Nothing here has been executed.**
No heater command, option change, Schedule or T-Comfort edit, extra Thermann
request or deployment was made. Thermowatt add-on 1.3.8 is unchanged and still
has `commands_enabled: false` and `on_demand_refresh_enabled: false`.

The owner accepts manual recovery if Home Assistant or the cloud fails, so a fully
automatic fallback is not a prerequisite. Manufacturer safety stays first.

## 0. Owner decision (11 Nov 2026) — supersedes the backstop in §1

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

T1 can test the Schedule park **without editing the Schedule**: it runs outside
the existing windows, where Schedule already parks the element (the 11 Nov
00:00–04:00 evidence). Emptying the programme is a later step, T4, approved
separately.

## 1. Recommendation in one paragraph (as originally proposed)

Use **Manual 70 °C as the "heat permitted" state and Schedule as the "parked"
state**, with the native Schedule reduced by the owner to **one late afternoon
backstop window** (proposed 13:00–16:00 local every day, no morning window).

- Both directions already exist in bridge 1.3.8: `/manual` carries an explicit
  70 °C target, `/auto` selects Schedule, and readback distinguishes them (`Cmd` 9 / 17).
- History shows that Schedule outside a window really holds the element off. It
  stayed off for four hours at a 16 °C reading.
- If HA fails while parked, the backstop still heats the tank before the evening
  peak at off-peak or solar cost. If HA fails in Manual, the heater behaves as a
  conventional 70 °C heater.

Genuine **Off/On while staying in Manual** (Option 1, the owner's preference) is
structurally the same pair of writes in this API (`Cmd` 9 ↔ 16). It cannot yet be
called reliable, because the resume path and what `Off` reports are unverified,
and a stuck Off gives no heat at all. Qualify it with the **app-only** observation
T2 below; it can then replace the Schedule park if the owner prefers to leave the
native programme alone.

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

| | **1. Off/On, stay Manual 70** | **2. Manual ↔ Schedule, empty Schedule** | **3. Manual ↔ Schedule, backstop window (recommended)** | 0. Today's Schedule + Manual boost |
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

**Why Option 3 over Option 1:**
- In this API both options are the same pair of mode writes, so they cost the same.
- Option 3 parks in a state already observed to work, and its park keeps a native
  backstop.
- Option 1's park disables both the windows and T-Comfort, and its resume and
  `Off` readback are unverified.

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

## 4. Proposed control policy (design; implementation is a later, separately approved PR)

1. **States.** `PARKED` = Schedule (`Cmd` 17) outside the backstop window.
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
   - ≤4 per day and ≤2 per opportunity;
   - no retries, and never the same intent twice;
   - after any unconfirmed result, stop automatic writes until the owner acknowledges.
5. **Confirmation:**
   - the bridge's immediate read, then the next poll;
   - physical confirmation from the 1-minute house meter: about +3 kW within two
     minutes of a permitted start at ≤62 °C, and about −3 kW at a stop.

   The vendor status alone is not physical proof.
6. **Recovery.** In every failure, stop automatic writes, keep the last confirmed
   state and alert the owner. The owner's manual route is the official app: select
   Manual (hot water now) or Schedule, or restore the original programme. An auth
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
| **T2** Off/On, app only (Option 1) | Owner in the app | From Manual 70 while heating, press power Off. Wait ≥1 poll (bridge must stay healthy). Press On. Wait ≥1 poll. Return to baseline | Element stops. Record exactly what `Cmd`/`T_SetPoint` Off reports. On returns to **Manual 70** (`Cmd` 9) and heating resumes at ≤62 °C. No `status_temperature_out_of_range` |
| **T3** API equivalence | Owner sets `commands_enabled: true` for the session only | One write per poll, published right after the STATUS update. Option 3: MODE `Manual`, then `Auto`. Option 1 (only if T2 passed): `off`, then `Manual`. At most 4 writes; no retry. Set `commands_enabled: false` afterwards | Each write is confirmed by the immediate or next poll and by the meter, exactly as in T1/T2. Request counts rise by 2 per write. No auth block |
| **T4** Backstop programme (Option 3) | Owner edits the Schedule in the app | Replace the windows with 13:00–16:00 daily (owner may choose the hours); keep T-Comfort 10. Restore the original if any issue | The backstop starts heating at ≤62 °C and stays off at >62 °C. No heating outside the window |
| **T5** Supervised trial | Separately approved executor PR | 1–2 weeks with commands enabled under the §4 limits; daily review of writes, confirmations, readiness and cost | Readiness goals met; ≤4 writes/day; zero unconfirmed writes; requests within plan |
| **T6** Failure drills | Owner | HA stopped while parked or in Manual; bridge restart between start and stop | Behaviour matches §3. The owner recovers using the app |

T1 and T2 involve **no API writes** and can run in either order. They show what the
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

## 7. Owner decisions requested

1. Accept Option 3 as primary, with Option 1 kept for T2 qualification; or prefer
   Option 1 if T2 passes.
2. Backstop hours: 13:00–16:00 daily, or longer on weekends or in summer.
3. Morning: no native window (cool water possible if HA fails, accepted manual
   recovery), or a short winter-only window.
4. Approve T0–T2 (app-only) first. T3 onward need separate approvals, including
   the `commands_enabled` change and the executor PR.
