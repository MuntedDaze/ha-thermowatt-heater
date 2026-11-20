# Thermowatt operating specification (proposed authoritative draft)

Audit base: `origin/main` **d137c4c** — Controller **0.17.1**, Thermann Hot Water
bridge **1.4.1**. Audit and report only: nothing was changed, merged, deployed
or operated. Paths below are relative to the repository root on that commit.

Status labels used in every table:

| Label | Meaning |
|---|---|
| **APPROVED** | An explicit owner decision exists (cited) |
| **IMPL** | What the code does today, with no specific owner decision behind it beyond "keep existing safeguards" |
| **HISTORICAL** | Exists only because of an older requirement; not current policy |
| **UNDECIDED** | No owner decision; see `3_OWNER_DECISIONS.md` |

Owner decisions relied on:

- D1 `docs/decisions/HOT_WATER_TEMPERATURE.md` (16 Nov): 45 overnight/weekend baseline, 62 weekday storage, optional 70 solar, existing peak-OFF policy, native protections unchanged.
- D2 This brief (20 Nov): **the 42 °C-by-07:00 and 45 °C-by-06:00 morning requirements are cancelled.** Manual 45 overnight; the native thermostat and its ~8 °C hysteresis manage the element; no bottom-probe chasing, no morning top-up, no morning deadline alarms. The owner accepts a bottom probe below 42 °C while Manual 45 is selected.
- D3 Weekend comfort window, confirmed 19 Nov (`docs/weekend/WEEKEND_STRATEGY.md`): 500 W PV is the preferred trigger, not a requirement; deadline fallback.
- D4 Owner's live peak policy is *Verified solar-only heating* (`docs/owner-report/OWNER_REPORT_2026-11-19.md` §1).
- D5 AGENTS.md approval gates (commands, auth, safety limits, automatic heating need owner approval).

**Key result of the audit: the active controller already conforms to D2.** No
active code chases 42 °C, schedules a morning top-up or raises a morning
deadline alarm. What remains are dead settings, their validation, stale
documentation, one mislabelled entity and one morning-time warning that needs
an owner choice (Decision 1).

---

## 1. Weekday overnight and daytime heating

| Period (household local time, owner's AEST tariff clock) | Trigger / measurements | Desired target | Restrictions | Settings | Implementation | Status |
|---|---|---|---|---|---|---|
| After evening peak → before morning peak (21:00 AEST ≈ 22:00 AEDT → 07:00 AEST ≈ 08:00 AEDT) | Clock only | **Manual 45** | Optional 70 only if solar qualifies (never at night in practice) | `baseline_c` (45), `baseline_start` (only used on days without an afternoon peak) | `simple_policy.py` `_policy` → "opportunity" branch, ~line 957 → `baseline` | APPROVED (D1, D2) |
| Morning peak (07:00–10:00 AEST) | Tariff calendar | **OFF** (Never policy) or verified solar-only heating (owner's live policy, D4) | Peak lockout precedes all economics; protective OFF bypasses spacing | `peak_heating_policy`, `peak_*` times, `peak_command_lead_minutes` (2) | `_policy` peak branch, ~line 744 | APPROVED (D1, D4) |
| After morning peak → evening peak | Bottom probe (fresh ≤ 75 min), EMHASS forecast, measured export, prices | **Manual 62** started at the cheapest window that still finishes by *peak − completion margin* (16:00 − 30 min = 15:30 AEST); 70 if solar qualifies | Never paused without a commissioned CT; latest start is firm | `normal_storage_c`, `completion_margin_minutes`, `pause_min_saving_aud`, forecast settings | `_policy` "deadline" branch, ~lines 868–955 | APPROVED (D1); timing method IMPL |
| Evening peak (16:00–21:00 AEST) | Tariff calendar | **OFF** or solar-only per D4 | as above | as above | peak branch | APPROVED |
| Day with no afternoon peak (flat tariff) | Clock | 62 by `storage_ready_time` (16:00), back to 45 at `baseline_start` (21:00) | — | `daytime_start`, `storage_ready_time`, `baseline_start` | `flat_deadline` ~line 851 | IMPL (generic/fresh installs; not the owner's tariff) |

**There is no morning top-up.** Before the morning peak the policy can only
return baseline 45 or (with qualified solar) 70. The retired morning fields are
never read by the policy (verified by search; see inventory).

## 2. Weekend

| Event | Desired | Implementation | Status |
|---|---|---|---|
| Overnight / until window opens | Manual 45 | `_weekend`, `simple_policy.py:214` | APPROVED (D1, D3) |
| First fresh (≤ `grid_max_age_seconds`), genuine PV report ≥ `weekend_pv_start_kw` (0.5 kW) | Window opens, latched (persisted across restart) | `pv_window_open` ~line 203 | APPROVED (D3) |
| Window open | Manual 62 at the cheapest forecast window that is ready by `storage_ready_time` − margin (15:30); off-peak grid assistance allowed; once selected never paused; no forecast → 62 immediately | `_weekend` lines ~298–330 | APPROVED (D3) |
| PV never opens window | Deadline fallback at the latest start (warm tank → at 15:30) | `opened_by = "deadline_fallback"` | APPROVED (D3) |
| Qualified surplus | Manual 70 (same boost test as weekdays) | `_boost` | APPROVED (D1) |
| `weekend_end_time` (18:00) | Manual 45 (does not cool stored water) | `weekend_day_ended` | APPROVED (D3) |
| Weekend peak | only if `weekend_peak` is on (owner: off, Aurora 93) | peak branch precedes weekend | APPROVED |

Retired by 0.17.0, still stored: `weekend_qualify_minutes`, `weekend_sunset_kw`, `weekend_sunset_minutes` (they now only size an internal PV sample buffer — no control effect).

## 3. Thermostat targets and native hysteresis

| Target | Role | Native behaviour | Status |
|---|---|---|---|
| OFF | Peak lockout, holiday, protective solar withdrawal | Software OFF; not proof of zero power; native protections remain | APPROVED |
| Manual 45 | Overnight/weekend baseline | Element runs when bottom probe ≲ 37 °C (45 − 8); probe may sit below 42 — accepted (D2) | APPROVED |
| Manual 62 | Weekday storage, weekend window, 12-hour Override | Reheats ≲ 54 °C | APPROVED |
| Manual 70 | Optional qualified solar boost | Reheats ≲ 62 °C; boost refused if probe already inside that band and no measured element power | APPROVED |

Hysteresis is a fixed planning constant `PolicySettings.hysteresis_c = 8.0`
(`simple_policy.py:59`). The controller never commands the element; the bridge
accepts only the 12 guarded `<target>@<prior>` transitions between these four
states (`thermowatt-heater/thermowatt_bridge.py:273`).

## 4. Tariff timing, AEST and Hobart daylight saving

- Owner's installation: `tariff_clock = standard` (fixed AEST UTC+10, preserved from the original install by `installation.py` `LEGACY_FACTS`). Peak times are entered in tariff-clock time (Aurora 93: 07:00–10:00 and 16:00–21:00 weekdays, weekends off-peak). During Hobart daylight saving these fall at 08:00–11:00 and 17:00–22:00 on the household clock. Conversion: `model.py` `tariff_at` / `tariff_zone`. **APPROVED** (tariff verified by owner).
- Household times (`daytime_start`, `storage_ready_time`, `baseline_start`, `weekend_end_time`) are always Hobart local (`time_zone`). **IMPL**.
- Fresh installs default to `local` clock and a flat tariff with zero prices (`installation.fresh_options`). **IMPL** (generic).
- Peak treatment: OFF from `peak − peak_command_lead_minutes` (2 min), plus a 15-minute command-slot reservation before it (`decide`, `simple_policy.py:578`). **APPROVED** (D1/D4).

## 5. EMHASS forecasting

- Inputs: `sources.forecast_pv` and `sources.forecast_load` (EMHASS `sensor.p_pv_forecast` / `sensor.p_load_forecast` via the template sensors in `shadow_controller/FORECAST_SETUP.md`). A flat measured household baseline sensor is also accepted for load. `forecast.py` `build_forecast` (~line 136).
- Net surplus per slot = min(inverter limit, PV × measured correction) × (1 − `forecast_uncertainty` 0.25) − load × 1.25 − `forecast_house_margin_kw` 0.3. PV is clipped to `pv_ac_limit_kw` (5 kW). Measured PV corrects the next 3 h only.
- Failure: forecast older than `forecast_max_age_minutes` (120), missing or malformed → no future solar assumed. Weekday required heating then starts at the latest start (or now if cheaper); weekend window starts 62 immediately; an alert fires after 60 minutes (`controller.py` `forecast_unavailable`). Unusable load forecast → conservative 1 kW floor (cannot authorise a boost).
- `forecast_enabled` is no longer a commissioning gate (four-state commissioning replaced it).
- Status: **IMPL**, consistent with D1. **Stale text:** the forecast alert still says "weekend solar heating rarely starts" (pre-0.17.0).

## 6. Solar production vs genuine grid export

| Measurement | Used for | Never used for |
|---|---|---|
| PV production (`sources.pv`) | Opening the weekend window only | Boost qualification (production ≠ surplus) |
| Signed grid power (`sources.grid`, sign from `import_positive`, requires `meter_verified`) | Boost qualification and withdrawal; required-heating window choice | Crediting nominal element watts as export |
| Circuit CT (`heater_power` + `heater_meter_verification`) | Verified element power; allows pausing selected 62 | — |

Implementation: `simple_policy.py` `add_pv` / `add_meter`; `runtime.py` ~270–300; `solar.grid_sanity`. **IMPL**, consistent with D1.

## 7. CT-free solar qualification and peak-only solar heating

- CT-free requires the exact commissioning record `ct_free_solar_verification = grid_entity|unit|direction|nominal_kW` matching the live mapping (`solar.ct_free_record`). **APPROVED** (supervised commissioning).
- Peak heating happens only under *Verified solar-only heating* (D4), only from a qualified surplus or an adopted qualified session, and exits on 10 min continuous import > 0.2 kW, meter loss, uneconomic export price or tank already at 70 (`_policy` peak branch). All are protective OFFs that bypass command spacing. **APPROVED**.

## 8. Boost lifecycle

| Phase | Rule (defaults) | Code | Status |
|---|---|---|---|
| Start | `optional_solar_boost` on; CT or CT-free record valid; meter fresh (≤ 120 s); fresh probe (≤ 75 min); probe ≤ 62 unless element power measured; **10 min of every report ≥ element_kw + export_headroom_kw (3.0 + 0.3 = 3.3 kW)**, gaps pause not reset (CT-free); finishes before peak − margin; saving ≥ max($0.10, extra kWh × $0.02); optional command budget; no cooldown; no unresolved protective exit | `_boost` ~635; `surplus_qualified` ~427 | APPROVED (D1); thresholds IMPL |
| Continue | While no 10-minute continuous import > 0.2 kW and measurement valid | `importing_continuously` ~418 | IMPL |
| Withdraw | Weekday deadline → back to 62; otherwise → 45; peak → OFF (protective) | `_policy` | IMPL |
| Cooldown | `solar_cooldown_minutes` (10) after any confirmed withdrawal | `controller.py:628, :806` | IMPL |

**Finding F1:** the 0.3 kW part of the 3.3 kW start threshold comes from
`export_headroom_kw`, which the catalogue labels **Retired** and exposes nowhere
(`executor.py:176`). It is active.

## 9. Smart polling and freshness

- Bridge schedules reads; the controller sends expiring v3 plans only when **both** the controller `polling_mode` and the app option `polling_mode` are `smart`/`minimum` (`executor.py` ~795, `adaptive.smart_plan:92`). Smart: quiet 45/OFF up to 90 min (8 h overnight), otherwise 15–30 min aligned, earlier before a decision. A dead controller drops back to fixed 30 min. Controller default is still `existing`. **IMPL** (Smart approved for release in 1.4.1; single-control question → Decision 2).
- Freshness limits (four overlapping numbers): command gate = poll interval + 5 min (35); `status_max_age_minutes` 45 (pre-peak warning, legacy planner gate); policy probe freshness 75 min (hard-coded); stale-status alert 2 × poll + 5 (65). Bridge: status ≤ 60 s before POST, refresh if older. **IMPL**.
- Request management: bridge `AuthGuard`, retry back-off, `min_cloud_retry_minutes`, 180 s poll reuse, proactive token refresh at 20 min; controller daily request budget (220) and 10-request exit reserve for optional starts. **APPROVED** (auth changes went through owner gates).

## 10. Owner holds, holidays, overrides, restarts, authentication

| Situation | Behaviour | Code | Status |
|---|---|---|---|
| App change seen (mode/target not commanded) | Owner override: no commands until *Resume* | `controller._check_external_change` | APPROVED |
| Hold button | Same | `set_hold` | APPROVED |
| Holiday dates (≤ 60 days) | OFF for the period, low-water warning suppressed | `set_holiday`, `decide` | APPROVED (0.7.0 requirements) |
| 12-hour Override | Manual 62 for 12 h (legacy saved 70 overrides honoured until expiry) | `start_guest` | APPROVED |
| HA restart | Never assumes last requested state; re-reads; unresolved command → fault lock until acknowledged | `restored`, `_confirm` | APPROVED |
| Authentication failure / lock | Bridge blocks cloud access; never auto-reset (owner bumps `auth_retry_generation`); controller gate `bridge_auth_not_authorized`, alert `cloud_fault` | bridge `AuthGuard`, `controller.gates` | APPROVED (PR #3 lineage) |

## 11. Command budgets, confirmation, protective OFF

- Optional (solar) starts stop at `controller_max_commands_per_day` (6 rolling 24 h); essential commands may go 6 further; **OFF is never budget-blocked**. 15-minute spacing except protective peak OFF.
- One publish per intent; bridge re-checks the exact prior state on a ≤ 60 s status, confirms with reads at 60 s and 300 s; never repeats a POST. Controller locks if unconfirmed within `controller_confirmation_timeout_minutes` (65).
- Protective exit is latched until OFF is confirmed; alerts `protective_exit_unresolved`, `peak_lockout_unverified`, `parked_off_cannot_restore`.
- Code: `controller.gates` ~853, `_confirm`, bridge `CONFIRM_FOLLOWUPS`. **APPROVED**.

## 12. Required storage when solar is insufficient

Weekday: 62 starts no later than *(peak − 30 min) − heating time* using nominal
3 kW physics (or slower measured watts), grid at off-peak price. Weekend: deadline
fallback (§2). A missed target raises `storage_target_may_be_missed` as a reason,
not an emergency; a confirmed 62/70 with the element verifiably idle 15 min and
probe ≥ 10 °C below target raises `storage_not_heating`. **APPROVED** (D1/D3).

## Warnings that touch the morning (relevant to D2)

| Warning | Trigger | Based on retired 42/45 rule? | Status |
|---|---|---|---|
| `pre_peak_low_hot_water` notification | Fresh bottom probe < `low_water_warning_c` (35) within `pre_peak_observation_minutes` (30) before **either** peak, including 07:00 AEST | No (35 °C, separate setting) — but it is a morning-time alarm on the bottom probe | **UNDECIDED** → Decision 1 |
| Entity `sensor.thermann_shadow_morning_availability` ("Morning hot water availability") | Same pre-peak assessment | No — only the entity name/label is historical | HISTORICAL name |
| `comfort.morning_availability()` (hard-coded 45 @ 06:00 / 42 @ 07:00) | Not called by production; only historical replays/tests | Yes | HISTORICAL — delete |
