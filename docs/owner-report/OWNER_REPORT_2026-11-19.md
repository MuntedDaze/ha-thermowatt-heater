# Owner report — 19 November 2026 development cycle

Base: `main` a41f8b1 (installed: Thermann Hot Water app 1.4.1, Controller
0.16.1). Nothing was deployed, restarted, reconfigured or operated. No live
Thermowatt service, credential or Home Assistant instance was contacted. All
evidence is offline: unit tests and synthetic replays through the real
controller and bridge code with a mocked cloud, MQTT and tank.

Three stacked PRs, all unmerged and awaiting owner approval. Merge them in order:

| PR | Version | Content | Classification |
|---|---|---|---|
| Solar delay | controller 0.16.2 | Two avoidable boost delays fixed; investigation; settings review | Automatic heating behaviour → approval required |
| Weekend window | controller 0.17.0 | Owner's weekend strategy | Automatic heating behaviour → approval required |
| Settings cleanup | controller 0.17.1 | Back navigation, one polling choice, legacy page, safe edits | Behaviour-preserving, but stacked → approval with the stack |

The bridge (app) stays 1.4.1 in all three; only the controller changes.

## 1. Morning solar delay (verified findings vs proposals)

**Not established:** the cause of the 19 November delay. That needs
timestamped live data (see "Live exports").

**Verified in code and synthetic replay.** The owner's live peak policy is
*Verified solar-only heating*, so the "Never during peak" lockout does not
explain 19 November.

- With solar-only peak heating, a clear weekday boosted the minute export
  qualified (09:00).
- **Fixed — recurring-boundary command count.** After a day with
  boost/withdraw churn, yesterday's 11:00 command still counted at today's
  11:00 decision. The optional budget looked full, 62 °C ran first, and 70 °C
  waited until 13:41. With 0.16.2 it starts at 11:00.
- **Fixed, then tightened after safety review — GoodWe `unavailable`
  reports.** Before 0.16.2, one valueless report erased the 10-minute 3.3 kW
  qualification. Now a gap pauses the timer: it never counts as export, only
  measured time counts, and no optional start is ever made on a tick whose
  latest meter report has no value. CT sites keep the 0.16.1 reset. Sessions
  keep the latched protective loss.
- **Plausible under solar-only, not proven:** GoodWe gaps *during* a peak
  solar session force protective OFFs and restarts. In replay this produced
  OFF/70/OFF churn, and the six-command budget then blocked boosts for about
  3 h. Also, export before 07:43 cannot start a boost that would not finish
  before the peak (07:11 → 07:58 in an early-export replay). Smaller holds:
  GoodWe balance inconsistency, one report below 3.3 kW, a warm tank,
  cooldown and spacing.
- Smart polling, the 8-hour quiet interval and pre-peak observations: no
  avoidable delay found.

**Proposals (not implemented):** P1 allow a qualified pre-peak start under
solar-only and let the peak rules govern it; P2 avoid "62 first" when export
is qualified; P3 decide in-session gap handling, and fix GoodWe polling
reliability first if gaps are frequent.

## 2. Weekend strategy (0.17.0)

Implemented as specified: 45 °C overnight; the first fresh measured PV report
of at least 500 W opens the window (no 15-minute delay, no 09:00 start); the
window stays latched until 18:00; 62 °C is scheduled economically with
EMHASS PV and household forecasts and must be ready by 16:00 (30-minute
margin), with off-peak grid assistance allowed; there is no pause once
selected; with no forecast heating starts now; 70 °C uses the existing
genuine-surplus test; at 18:00 the target returns to 45 °C.

**Deadline fallback, confirmed by the owner (19 Nov).** 500 W PV is the
preferred trigger, not an absolute requirement. If PV never opens the window
and the tank needs heat, 62 °C starts at the latest start (about 12:46 on
cloudy replays) using weekend off-peak electricity. Tests prove it:
- opens only when the tank needs heat, never on a status older than 35 min;
- sends each command once (62 then 45, or nothing for a warm tank);
- yields to owner hold, holiday, the 12-hour Override, the cloud gate,
  command spacing, a configured weekend peak and the weekend switch;
- is essential heat, so it never uses the optional solar budget.

Replays: spring, summer and winter clear; cloudy; partly cloudy; missing
forecast; restart; stale PV meter; pessimistic forecast. 62 °C was reached
before 15:30 on every day, the target was 45 °C after 18:00, and there were at
most three commands a day.

Limits: the Thermann reading is a single bottom probe and the setpoint is a
thermostat request. Returning to 45 °C does not cool stored water.

## 3. Code and settings cleanup (0.17.1)

There are 99 setting keys: 33 already retired, 10 legacy/developer (now on
their own page), 56 required. There is one homeowner polling choice; the
controller and app modes must both say Smart (proposal: let the controller
follow the app). Back navigation is in every submenu. Five harmless
preferences can now be edited while Automatic is on. Two unreferenced
definitions were removed. No stored key, entity or MQTT identity changed.
Details: `docs/cleanup/AUDIT.md`.

## 4. Settings recommendations (no live change made)

| Proposal | Recommendation | Evidence |
|---|---|---|
| Commands cap 6 → 8 | **Keep 6** (owner agreed 19 Nov). 8 would be an interim only while still on 0.16.1 | Replays: 8 changes nothing on 0.16.2; on 0.16.1 it only masks the count error |
| Household forecast → `sensor.hot_water_load_forecast_input` | **Keep the existing mapping** (owner agreed 19 Nov). **Not yet.** The recorded EMHASS config forecasts yesterday's whole-house load, which includes the heater (no deferrable loads, no CT) | Replay: boost 11:00 → 12:08. Read-only checks to make first are in `SETTINGS_REVIEW.md` |

Reducing transitions (in-session gap withdrawals, patchy-day churn) is a
better lever than raising the cap.

## Live exports needed (read-only, soon)

1. Controller diagnostics download, which includes the owner event log, peak
   policy, polling mode and command list.
2. HA history CSV for 19 Nov 05:00–15:00: GoodWe grid, PV, PV AC and house;
   Thermann temperature, target and mode; last poll; cloud health; controller
   status.
3. Thermann Hot Water app log for the same window.

## Outstanding live tests (owner-supervised, after approval)

- Install the controller only (app unchanged). Confirm the version in the
  copyable report and that entities, history and settings are intact.
- First weekday: observe the 11:00 decision and `commands_24h` in events.
- First weekend: window opening time and basis, 62 °C timing, 18:00 return to
  45 °C.
- Check the configuration menus: Back on each submenu and the Legacy page.

## Deployment and rollback

Deploy only after approval. Use the existing controller in-place update
(`docs/audits/UPGRADE_1_4_1.md` pattern: copy `custom_components/thermann_shadow`,
restart HA, check the report). Turn Automatic off during the restart window if
preferred.

Rollback: reinstall the previous controller folder (0.16.1 from `main`
a41f8b1) and restart. Stored options and entities are unchanged by all three
releases. 0.17.x adds no stored keys, so 0.16.1 reads them as before. The
weekend latch dates already exist in 0.16.1 storage.
