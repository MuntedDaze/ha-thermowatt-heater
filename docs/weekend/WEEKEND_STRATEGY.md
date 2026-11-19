# Weekend comfort window (controller 0.17.0)

The owner's weekend policy, as implemented. Weekday behaviour and the tariff
treatment are unchanged; the fixed AEST tariff clock still converts to Hobart
daylight-saving time exactly as before.

## Policy

| Time / event | Thermostat request | Notes |
|---|---|---|
| Overnight, and until the window opens | Manual 45 | Baseline. |
| First fresh measured PV report ≥ 0.5 kW | window opens | One report is enough: no 15-minute qualification and no 09:00 start restriction. The report must be current (≤ 3 min), genuine (not restored) and numeric. |
| Window open | Manual 62, scheduled | Planned to be ready by `storage_ready_time` (16:00) less the 30-minute completion margin, using the EMHASS PV and household-load forecast to choose the cheapest start. Off-peak grid assistance is permitted. Once 62 is selected it is not paused. |
| Window open, no usable forecast | Manual 62 now | Conservative fallback: start immediately rather than wait blind. |
| PV never opens the window | Manual 62 at the latest start | Firm deadline fallback, so evening hot water is not left to the weather. A cold tank (or an unknown reading) opens early enough to reach 62 by the soft target; a warm 55–61 °C tank opens at the soft target (15:30). **Confirmed by the owner on 19 November 2026**: 500 W PV is the preferred trigger, not an absolute requirement. |
| Genuine surplus qualifies | Manual 70 | Unchanged optional-boost test: 10 minutes of ≥ 3.3 kW measured export, economics, budgets, cooldown and withdrawal guards. |
| Clouds, PV below 0.5 kW after opening | unchanged | The window stays latched until the end time. (The previous low-PV "sunset" early end is no longer used.) |
| 18:00 (`weekend_end_time`) | Manual 45 | The thermostat target returns to baseline. This does **not** cool water already stored; the tank cools by use and standing loss. |

A restart keeps the day's latch (it is saved with the controller state). A
configured weekend peak, if any, still takes precedence.

## Deadline fallback safeguards

Tested in `tests/test_weekend_window_0_17_0.py`:

- **No unnecessary heating.** Manual 62 is a thermostat request: the native
  thermostat heats only when the bottom probe is about 8 °C below it (≤ 54 °C).
  A command is never sent on an old status: the controller gate requires a
  status no older than the fixed poll interval plus 5 minutes (35 minutes by
  default), otherwise the wanted command first triggers a fresh read. The app
  also re-reads the heater's exact mode immediately before any command. On
  the real controller, a cloudy Saturday with a 60 °C tank sent 62 at 15:30
  and 45 at 18:00 and the element never ran.
- **No repeated commands.** Once 62 is selected it is held and never paused;
  the window latch survives restarts; 18:00 ends the day and the end latch
  prevents reopening. A cloudy Saturday with a 40 °C tank sent exactly
  Manual 62 then Manual 45.
- **Existing safeguards first.** Owner hold, holiday and the 12-hour Override
  take precedence; the cloud/freshness gate and 15-minute command spacing
  hold it; a configured weekend peak still parks the heater and moves the
  deadline earlier; switching off *Weekend solar-led normal storage*
  disables it. It is essential (required) heat, not an optional solar start,
  so it never consumes the optional solar budget. All controller gates
  (commissioning, essential command cap, request budget, exact-prior
  confirmation) apply unchanged.

## Warm tank (55–61 °C bottom probe) on a day without PV

Independent review, 19 November 2026. A 55–61 °C reading is inside the native
8 °C hysteresis of a 62 target, so neither 45 nor 62 adds heat at that moment,
and the controller cannot raise it to 62 without selecting 70 (which is
reserved for qualified solar surplus). The difference is what happens next:

- **Kept at 45** (the first 0.17.0 rule): the native thermostat would not
  reheat until about 37 °C. An afternoon draw would be noticed only at the
  next cloud reading, and Smart polling checks a quiet baseline as rarely as
  every 90 minutes, so evening water could be well below normal storage.
- **Selected 62 at the soft target** (the intended rule): the thermostat
  itself reheats any draw that takes the probe to 54 °C or below, before
  18:00, with no poll needed. No heat is added otherwise; the cost is the same
  two commands (62, then 45 at 18:00) as any weekend day.

The review also found that the first rule depended on polling timing: a
reading that aged past 45 minutes at the deadline was treated as unknown, the
window latched, and 62 was requested anyway. The intended rule removes that
dependence: the window always opens by the latest start, and the reading only
decides how early. Replay with a 58 °C tank and a 3 kWh draw at 16:30: the
probe fell to 49.6 °C and was reheated to 61.6 °C by 18:00.

The bottom probe is not a whole-tank temperature. "62 available" means the
thermostat is maintaining a 62 target, not that every litre is at 62 °C.

## Retained settings

`weekend_qualify_minutes`, `weekend_sunset_kw` and `weekend_sunset_minutes`
no longer affect control. They are kept, validated and restored by rollback so
saved configuration and entity IDs are unchanged; their descriptions say so.

## Limits of a bottom probe and a thermostat target

- The Thermann reading is a single bottom-of-tank probe (`T_Avg`), polled from
  the cloud. It is not a whole-tank or outlet temperature and can lag a heating
  cycle or drop sharply after a draw.
- Manual 62 or 70 is a thermostat request. The heater's native thermostat
  decides when the element runs (it reheats roughly 8 °C below the target), so
  selecting 62 on a warm tank may not energise the element at all.
- "Reached 62" in the replay is the simulated uniform tank, not a measurement.
- Software cannot certify whole-tank temperatures; regular high-temperature
  operation (62 every weekend day, 70 when solar qualifies) is retained as the
  owner's agreed strategy (see `docs/decisions/HOT_WATER_TEMPERATURE.md`).

## Evidence (synthetic)

`tools/weekend_replay.py` runs a full week through the real controller and
bridge 1.4.1, then reports each weekend day. Production forecast haircut,
CT-free commissioned grid meter, Smart polling, 08:00 and 19:00 showers plus a
Saturday evening bath.

| Scenario | Window opened | 62 requested | 62 reached | 70 | 18:10 target | Commands/day |
|---|---|---|---|---|---|---|
| Spring clear (Nov, AEDT) | 06:05 measured PV | Sat 06:05 (warm tank), Sun 08:41 (cheapest) | 09:11 / 10:58 | 09:22 / 11:09 | 45 | 3 |
| Summer clear (Jan) | 06:17 | 06:17 / 08:42 | 09:11 / 10:59 | 09:22 / 11:10 | 45 | 3 |
| Winter clear (Jul, AEST) | 08:12 | 09:28 | 11:43 / 11:37 | — | 45 | 2 |
| Spring cloudy (PV ≤ 0.4 kW) | 12:46 deadline fallback | 12:47 | 14:05 / 15:01 | — | 45 | 2 |
| Winter cloudy | 12:46 deadline fallback | 12:47 | 15:07 / 15:01 | — | 45 | 2 |
| Spring partly cloudy (≤ 1.5 kW) | 06:05 | 06:05 / 06:09 | 09:11 / 09:24 | — | 45 | 2 |
| Missing forecast | 06:05 | 06:05 / 06:06 (start now) | 09:11 / 09:21 | — | 45 | 2 |
| Restart Saturday 10:30 | as spring clear | identical | identical | identical | 45 | 3 |
| PV entity stale Sat 05:00–10:00 | Sat 10:00 (when fresh) | — (70 at 09:01 on measured export) | 10:13 | 09:01 | 45 | 2 |
| PV forecast 50 % of actual | 06:05 | 06:05 / 07:11 | 09:10 / 10:28 | — | 45 | 2 |

Every simulated day reached 62 before the 15:30 soft target and returned to
45 after 18:00, with at most three commands a day (well inside the six-command
rolling cap). These are synthetic results, not measured weather or demand.
