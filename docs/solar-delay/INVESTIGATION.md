# Delayed morning solar boosts: investigation (controller 0.16.1 → 0.16.2)

Date: 19 November 2026. Base: `main` a41f8b1 (bridge 1.4.1, controller 0.16.1).

## What this is and is not

The owner reported that on Thursday 19 November 2026 substantial surplus solar
appeared available before the 70 °C boost began. **No live data for that day is
in this repository**, so this document does **not** claim what caused that
delay. It lists every code path that can hold a morning boost, measures each
one with a synthetic replay through the real controller and bridge, fixes the
two that are avoidable, and names the exports that would identify the actual
cause.

## Every condition that can hold a 70 °C start

Order follows `SimplePolicy._boost` and the controller gates. "By design"
means the behaviour is an intended protection or owner setting.

| # | Condition (code) | Effect on a morning boost | Classification |
|---|---|---|---|
| 1 | Peak lockout, `peak_heating_policy = Never` (`peak_lockout`, `peak_heating_locked_out`) | Weekday morning peak is 07:00–10:00 AEST = **08:00–11:00 AEDT**. No heating at all; the earliest boost is 11:00. | By design (owner setting) |
| 2 | `boost_cannot_finish_before_peak` | Before 08:00 AEDT the boost must finish 30 min before the peak. 45→70 °C takes about 3 h at 3 kW, so a pre-peak start is effectively never allowed. | By design |
| 3 | `peak_command_reserved` | 07:43–07:58: no new start that would need a second command at the peak boundary. | By design |
| 4 | `sustained_full_solar_required` | Every GoodWe report for 10 minutes must show ≥ 3.3 kW available export. One report below 3.3 kW restarts the 10 minutes. | By design (measured-export protection) |
| 5 | GoodWe `unavailable`/`unknown` report | **0.16.1: erased all qualification votes, even before any session.** | **Avoidable — fixed in 0.16.2** |
| 6 | `verified_circuit_and_grid_required` | No start on a tick whose latest grid report has no value or is > 3 min old. | By design (unchanged) |
| 7 | GoodWe whole-site consistency (`grid_sign_or_whole_house_balance_inconsistent`, `export_exceeds_measured_inverter_output`, `inverter_or_house_reading_implausible`) | Blocks the start on that tick only; it does not reset qualification. Persistent PV/house/grid timing skew would block repeatedly. | By design; check live data |
| 8 | Implausible export (> 110 % of the 5 kW inverter) | Resets qualification. | By design |
| 9 | `optional_budget_reserved_for_essential_heat` | Optional starts stop when the rolling 24 h count reaches the cap (6). **0.16.1 used the count from the previous tick with an inclusive 24 h boundary, so yesterday's 11:00 boundary command still counted at today's 11:00 decision.** | **Avoidable — fixed in 0.16.2** (cap unchanged) |
| 10 | `optional_exit_request_reserve` | Optional start needs 10 spare HTTP requests in the 220 budget. Smart polling uses far fewer. | By design |
| 11 | `command_spacing` (15 min) | After the 11:00 boundary command, a 62→70 step must wait 15 min. | By design |
| 12 | `solar_withdrawal_cooldown` (10 min), `protective_exit_unresolved` | After a withdrawal. | By design |
| 13 | `fresh_temperature_required` | Temperature older than 45 min (runtime) is unknown. Smart polling asks for a read as soon as export qualifies (`_event_decision_at`), and at every tariff boundary; the replay shows no delay from this. | By design; no avoidable delay found |
| 14 | `heater_status_too_old`, `bridge_refresh_budget_exhausted`, confirming state | Gate a command until a read; the wanted command itself schedules the read. | By design |
| 15 | `inside_native_hysteresis_no_verified_heat` | Without a heater CT, 70 °C is not requested while the tank reads above 62 °C because the thermostat would not cut in. | By design (physics) |
| 16 | `boost_value_below_switching_margin` | Saving uses measured export for 30 min and the EMHASS forecast after that (25 % PV haircut, load × 1.25 + 0.3 kW). A high or flat household forecast, or a pessimistic PV forecast, rejects the boost; the required 62 °C start then runs first. | By design, but sensitive to the load-forecast mapping (Priority 4) |
| 17 | "62 °C first" on a CT-free installation | Once required 62 °C heating is running, the element absorbs 3 kW, so measured export cannot reach 3.3 kW on a 5 kW inverter. 70 °C waits until 62 °C is reached. | Consequence of 9, 16 or a gap at the decision tick |
| 18 | In-session GoodWe gap | A valueless report during an active 70 °C session latches a loss and withdraws to 62 °C (two extra commands, cooldown). | By design (kept unchanged); see proposals |
| 19 | Weekend 09:00 start, 15-min PV qualification | Weekend only. | Replaced by the weekend PR |

Smart v3 polling: the 8-hour quiet interval applies only while the state is a
stable baseline/OFF before 09:00 or after 21:00. It never makes temperature
fresh, and a qualified surplus or a wanted command schedules a read. The
pre-peak observation (30 min before the peak) and the boundary reads are
early enough: no replay showed a stale-temperature delay. The previously
rejected proactive Resume refresh was **not** reintroduced.

## Synthetic replay (`tools/morning_solar_delay_replay.py`)

Monday 16 – Thursday 19 November 2026 through the real controller, the real
bridge 1.4.1 and the mocked cloud; CT-free commissioned grid meter, Smart
polling, production forecast haircut and margin, 315 L / 3 kW tank, showers
07:00 and 19:00, PV clipped at 5 kW. Times are AEDT on Thursday.

| Scenario | Export first qualified | 0.16.1: Thursday commands | 0.16.2: Thursday commands |
|---|---|---|---|
| Clear, peak Never | 09:00 | OFF 07:58, **70 at 11:00** | unchanged |
| Clear, peak solar-only | 09:00 | OFF 07:58, **70 at 09:00** | unchanged |
| Patchy Wednesday, clear Thursday | 09:00 | OFF, **62 at 11:00, 70 at 13:41** (`optional_budget_reserved_for_essential_heat`) | OFF, **70 at 11:00** |
| One GoodWe `unavailable` every 7 min (06:00–12:00) | 13:07 (0.16.1) / 09:00 (0.16.2) | OFF, **62 at 11:00, 70 at 13:07** | OFF, **70 at 11:00**, in-session gap withdraws at 11:17, 70 again 13:07 |
| Passing cloud (45 % PV for 1 min every 9 min) | 13:31 | OFF, 62 at 11:23, 70 at 13:31 | unchanged (genuine measured shortfall) |
| Household forecast flat 1.2 kW | 09:00 | OFF, 62 at 11:00, 70 at 13:06 (`boost_value_below_switching_margin`) | unchanged |
| PV forecast 60 % of actual | 09:00 | OFF, 62 at 11:00, 70 at 13:06 | unchanged |
| Command cap 8 (clear day) | 09:00 | OFF, 70 at 11:00 | unchanged — cap not binding |

What this shows (synthetic, not live evidence):

- With peak policy *Never*, a clear weekday always waits for 11:00 AEDT.
  This is the single largest delay and it is an owner setting, not a defect.
- After a day with boost/withdraw churn, the recurring-boundary count made
  the optional budget appear full at exactly 11:00; the required 62 °C start
  then ran first and 70 °C waited about 2¾ h. Fixed.
- GoodWe valueless reports cost about 2 h before a session. Fixed. During a
  session they still withdraw (kept; see proposal P3).
- Forecast quality decides whether 11:00 goes straight to 70 °C or to 62 °C
  first. Raising the command cap does not change any of these mornings.

## Changes in 0.16.2

1. `Controller.commands_in_window(now)` counts commands in `(now − 24 h, now]`.
   The policy's `optional_allowed` and the controller gate both use the
   decision time. Cap 6, essential allowance (+6), request reserve and the OFF
   exemption are unchanged.
2. A current GoodWe report with no value is a gap. Before any optional
   session or unresolved optional intent it neither votes nor erases earlier
   votes. Unchanged: no start on that tick, 3-minute gap and freshness
   limits, reset on implausible/unverified/uncommissioned reports, and the
   latched protective loss during a session (peak withdrawal included).
3. Owner events add `gate` (the command gate holding a wanted change) and
   `commands_24h`.

Classification: changes automatic heating behaviour and the command-limit
boundary → **owner approval required** before merge.

## Effect on the existing week and seasonal evidence

The four committed replay result files were regenerated. All non-CT runs are
identical. CT runs differ by one or two status reads (fewer in most). One run
changes materially: winter, fixed 60-minute polling, dedicated CT. With
0.16.2 the Thursday post-peak start goes straight to 70 instead of 62 first,
so on Friday the heater is at 62 rather than 70 when the replay's deliberate
synthetic cloud outage refuses the pre-peak OFF. Both versions fault-lock
exactly as designed and the heater stays in its last state through that peak
(peak import 3.93 → 4.08 kWh, two more commands across the week, +$0.09).
This is the existing designed outage scenario, not a new hazard.

## Proposals (not implemented)

- **P1 — peak policy.** If morning peak solar matters, *Verified solar-only
  heating* removed the 08:00–11:00 delay in replay (70 °C at 09:00). It keeps
  measured-import withdrawal and the exact-prior protocol. Owner decision.
- **P2 — avoid "62 °C first" at 11:00.** When export is qualified but the boost
  is judged marginal, the required 62 °C start blocks a later 70 °C on CT-free
  sites until 62 °C is reached. A design option is to defer the required start
  while measured export is qualified and the latest start is hours away. Not
  implemented: it changes required-heat timing.
- **P3 — in-session gap tolerance off-peak.** A ≤ 3-minute valueless gap during
  an off-peak 70 °C session could hold rather than withdraw (peak latch
  unchanged). Saves two commands per blip. Not implemented: it relaxes a
  measured-export protection and needs an explicit decision.

## Settings questions

See `SETTINGS_REVIEW.md`: keep the six-command cap with 0.16.2 (eight only
masks the boundary-count error on 0.16.1), and do not map the EMHASS
household forecast until it excludes the heater.

## Live exports needed to explain 19 November (read-only)

All read-only; no restart, setting change or command. Export soon: the owner
event log keeps only the last 200 semantic events.

1. **Controller diagnostics** (Settings → Devices & services → Thermann
   Controller → ⋮ → Download diagnostics) or the copyable owner report. It
   contains the owner events with `boost_reason`, controller state, command
   status and timestamps, the current command count, gate failures and the
   saved peak policy, CT-free verification and polling mode.
2. **History CSV, 19 Nov 05:00–15:00 AEDT** (History → select → Download):
   the GoodWe grid/meter power entity, PV power, PV AC, house load, the
   Thermann water heater (temperature, target), mode, last successful poll,
   cloud health, the controller status/decision sensors.
3. **Thermann Hot Water add-on log** for the same window (poll-plan
   acceptance, reads, POST and confirmation lines; no credentials are logged).
4. The Wednesday 18 Nov command list (in the diagnostics), to check the
   rolling count at Thursday's decision times.

With those, the delay is the interval between the first minute every
GoodWe report showed ≥ 3.3 kW export for 10 minutes and the 70 °C POST,
attributed minute by minute to the `boost_reason`/gate in force.
