# Live Thermowatt Cloud Outage & Recovery Investigation (25 November 2026)

## Incident summary & confirmed live outcome

- **Observed outage time:** ~22:00 Hobart (AEDT, UTC+11; `21:00` AEST fixed tariff clock = end of Aurora Tariff 93 evening peak, when policy transitions from `OFF` to overnight `Manual 45 °C` baseline).
- **Installed bridge:** `1.5.0` (with Controller `0.18.1`).
- **Confirmed live recovery telemetry (25 November 2026, ~23:45 Hobart):**
  - The 3,600-second (1-hour) cloud backoff expired and the **bridge recovered cleanly** without manual intervention:
    - `cloud_health`: `ok`
    - `auth_guard_mode`: `authorized`
    - `last_successful_poll`: `23:30`
  - The **controller locked** as predicted by the boundary-race analysis (Race A):
    - Heater: `Off`, bottom temperature `18 °C`
    - Controller state: `fault_locked`
    - Fault: `command_not_applied`
    - Original `Manual:45@off` request created at `22:00`, resolved as `not_applied` at `23:00`
    - `sent_at`: `null` (zero confirmed heater command POST for the failed transition)
  - Owner manually restored heating via the official Thermann app with automatic control disabled while fixes are developed and tested offline.

**What the live outcome confirmed:**
1. The `22:00` `cloud_success_false` was a **transient cloud response**, not an expired-token lockout (`AuthGuard` remained `authorized` and the 1-hour recovery poll succeeded without refreshing tokens — so Fix #4 / proactive refresh on `cloud_success_false` is **not** needed).
2. The exact root cause of the unrecovered overnight heater was **Race A** (the synchronous `22:00:00` collision between Smart polling's `GET /status` and the controller's `Manual:45@off` publish, compounded by `_offline()` silently draining `self.commands` without updating `last_command`, followed by `late_poll` locking the controller at `23:00` with the misleading `command_not_applied` message claiming the command "was sent").

---

## Findings across the 7 investigation questions

### 1. Why the cloud returned `success: false` (confirmed causes vs hypotheses)

**Confirmed from code ([`thermowatt_bridge.py`](../../../thermowatt-heater/thermowatt_bridge.py)) and live recovery:**
- `cloud_success_false` is raised by `MyThermowattBridge._result()` (lines 686–704) when HTTP status is `200–299`, the response is a JSON `dict`, `daily_limit(body)` (`body.get("error") == "Daily request limit exceeded"`) is `False`, and `body.get("success") is False`.
- `body.get("success") is False` is checked before `body.get("error")`, and `safe_diagnostic()` intentionally suppresses raw vendor strings so sensitive response content can never be logged.
- Because the HTTP status was `2xx`, `AuthGuard` stayed `authorized` and `tick()` entered the normal 3,600-second status-poll backoff (`failures = 1`).
- The clean ~23:00 bridge recovery (`cloud_health: ok`, `auth_guard_mode: authorized`) confirms the `22:00` failure was transient and **not** an authentication lockout or persistent token expiry.

**Remaining hypotheses for the vendor's transient `success: false`:**
1. **Most likely:** Transient MyThermowatt/Ariston cloud backend error or brief heater-to-cloud connectivity gap on `GET /status`.
2. **Possible:** Short-lived vendor-side rate-limit/maintenance response with an `error` string other than the exact literal `"Daily request limit exceeded"`.

### 2. Could current polling and token-refresh frequency contribute to cloud rejection?

- **Unlikely.** Bridge `1.5.0` Smart mode reduces both polling and token-refresh volume (90 min daytime / 8 h overnight quiet intervals, woken at policy transitions; ordinary Smart `GET /status` skips proactive 20-minute token refresh and only refreshes reactively on HTTP `401`). The clean 1-hour recovery without any token refresh confirms auth/polling frequency did not cause a lockout.

### 3. Are scheduled heating requests retained, retried, and confirmed after cloud recovery?

- **Before fixes:** Only if the outage happened *before* the controller published (`change_requested`). Under the `22:00:00` boundary race (Race A: `_offline()` silently drained `self.commands`; Race B: command sat in `self.commands` for 60 min until `dropped_command_older_than_30s`; Subcase C: pre-command `command_status_refresh` failed), the controller locked into `fault_locked` and never retried `Manual:45@off`.
- **After approved fixes #1, #2, #3:**
  - Fix #3 advances Smart pre-transition reads 30 s ahead of non-peak boundaries (`21:59:30`), so failing polls report `backoff` before `22:00:00` and healthy reads remain `<= 60 s` fresh through `22:00:00` + `COMMAND_INTERVAL` (0 extra GETs).
  - Even if a race or pre-command refresh failure still occurs, Fix #1 reports explicit `refused_cloud_backoff` immediately (never silently draining or stalling for 60 min), and Fix #2 defers proven-never-sent transient backoff refusals back to `change_requested` (preserving `self.heater` and `parked_off_restore_since`), so the controller **automatically applies and confirms `Manual:45@off`** as soon as the cloud recovers.

### 4. Can an essential heating request remain pending indefinitely or be lost during an outage?

- **Pending indefinitely? No.** Bridge `self.pending` expires at `CONFIRM_DEADLINE = 360 s`; controller `self.intent` expires at `confirmation_timeout_minutes = 65.0` (or earlier on `late_poll` / `bridge_failure`).
- **Lost on transient boundary outages? Prevented by Fixes #1–#3.** Uncertain POSTs, auth lockouts, quota limits, policy refusals, and broker-dropped publishes still fail closed to `fault_locked`, and `parked_off_cannot_restore` continues to warn at 30 minutes (now continuously even across `command_spacing` holds).

### 5. Will the controller return to normal automatic operation without manual intervention?

- **Observed live on 25 Nov 2026 (pre-fix):** Bridge recovered cleanly (`ok` / `authorized`); controller locked (`fault_locked` / `command_not_applied`) as predicted.
- **With Fixes #1–#3:** Both bridge and controller return to normal automatic operation (`baseline_45`) after a 1-hour (or 3-hour doubled) transient backoff without manual intervention, while still failing closed to `fault_locked` for auth, quota, policy, or uncertain POST failures.

### 6. Are repeated status failures producing excessive duplicate notifications?

- Continuous backoff already deduplicates via `notification_cooldown_hours = 6.0`.
- **Fixed by Fix #5:** `Controller.alert_cooldowns` now preserves cooldown timestamps separately from active/resolved notification keys (`Controller.alerts`), preventing brief `cloud_health = unavailable` (`None`) or flapping ticks from resetting the 6-hour cooldown.

### 7. Implemented approved fixes (#1, #2, #3, #5 + honest fault wording)

All approved fixes preserve the agreed 45/62/70 °C heating policy, peak-OFF rules, solar-boost lock, `AuthGuard`, exact-prior checks, zero-retry POST safety, and zero extra cloud requests:

1. **Fix #1 — Bridge explicit queue refusal ([`thermowatt_bridge.py`](../../../thermowatt-heater/thermowatt_bridge.py)):**
   - Added `_drain_commands(reason, error)` used by `_offline()` and by `tick()` when in `backoff` / `quota_limited` cooldown (never during healthy 20 s `COMMAND_INTERVAL` pacing).
   - Never overwrites `last_command` when `self.pending is not None` (uses `refused_while_pending` instead).
   - Reports `refused_cloud_backoff`, `refused_cloud_quota_limited`, `refused_auth_not_ready`, or `dropped_bridge_offline` instead of silently discarding or stalling queued commands for 60 minutes.
2. **Fix #2 — Controller safe deferral on proven-never-sent transient backoff ([`controller.py`](../../../custom_components/thermann_shadow/controller.py), [`report_codes.py`](../../../custom_components/thermann_shadow/report_codes.py)):**
   - Added strict fail-closed `TRANSIENT_REFRESH_ERRORS` allowlist and `_transient_backoff_refusal()`.
   - Defers `refused_cloud_backoff` and allowlisted transient `refused_status_refresh_failed` (only when `bridge_confirmation_pending is False`, `auth_mode == "authorized"`, and `cloud_health` is not `auth_locked`/`quota_limited`) as `deferred_cloud_backoff` without entering `fault_locked`.
   - Keeps `parked_off_restore_since` continuous across `command_spacing` / `cloud_or_freshness_gate` holds when `want.plan["wanted"]` is a heating target.
   - All auth, quota, policy, dropped, rejected, unclassified, late-poll, and timeout failures remain strictly `fault_locked`.
3. **Fix #3 — Executor pre-transition Smart poll lead ([`executor.py`](../../../custom_components/thermann_shadow/executor.py)):**
   - Added `TRANSITION_POLL_LEAD = timedelta(seconds=30)` for non-peak tariff and flat-tariff transition boundaries (`21:59:30` before `22:00:00`), avoiding the synchronous collision while keeping healthy status `<= 60 s` fresh through `COMMAND_INTERVAL`.
4. **Fix #5 — Controller notification cooldown preservation ([`controller.py`](../../../custom_components/thermann_shadow/controller.py)):**
   - Added backwards-compatible persisted `alert_cooldowns` dict so brief `unavailable` / flap cycles cannot erase the 6-hour cooldown.
5. **Honest fault wording ([`controller.py`](../../../custom_components/thermann_shadow/controller.py)):**
   - Updated `command_not_applied` (`RECOVERY` + notification detail) and `confirmation_timeout` notification detail to state that the MQTT command was **published** (not falsely claiming it "was sent" when the bridge never confirmed sending or applying it).
6. **Fix #4 (proactive token refresh on `cloud_success_false`):** Intentionally **not implemented** — live recovery confirmed the `22:00` error was transient and authentication recovered cleanly without changing token handling.

---

## Deterministic regression tests

Updated [`tests/test_cloud_outage_recovery.py`](../../../tests/test_cloud_outage_recovery.py) and [`tests/test_parked_off_warning.py`](../../../tests/test_parked_off_warning.py) covering clean pre-transition outage, live-incident Races A & B, pre-command transient refresh deferral, fail-closed locks for all 12 non-transient/auth/quota refusal combinations, honest `"published"` fault wording, 30-second Smart poll lead with 0 extra pre-command GETs, 1-hour -> 2-hour doubled backoff failure-to-recover, 65-minute confirmation timeout, and 6-hour notification cooldown preservation across `unavailable` gaps.
