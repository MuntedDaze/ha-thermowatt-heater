# Live Thermowatt Cloud Outage & Recovery Investigation (25 November 2026)

## Incident summary

- **Observed time:** ~10:00 PM Hobart (AEDT, UTC+11; `21:00` AEST fixed tariff clock = end of Aurora Tariff 93 evening peak, when policy transitions from `OFF` to overnight `Manual 45 °C` baseline).
- **Installed bridge:** `1.5.0` (identical in `main` and `dev`; PR #55 makes no bridge or controller changes).
- **Observed symptoms:**
  - Bridge `1.5.0` received `cloud_success_false` during a status poll and entered a **3,600-second (1-hour) backoff**.
  - Controller requested the overnight `45 °C` baseline (`Manual:45@off`), which remained **published and unconfirmed** (`state = confirming`, `pending_intent.status = "published"`).
  - Last confirmed heater state was `Off`, and the official Thermann app independently confirmed the heater remained `Off`.
- **Owner live test:** Left untouched to observe automatic recovery at ~11:00 PM. No live HA or cloud interaction was performed by this investigation.

---

## Findings across the 7 investigation questions

### 1. Why the cloud returned `success: false` (confirmed causes vs hypotheses)

**Confirmed from code ([`thermowatt_bridge.py`](../../../thermowatt-heater/thermowatt_bridge.py)):**
- `cloud_success_false` is raised exclusively by `MyThermowattBridge._result()` (lines 686–704) when:
  1. HTTP status is `200–299`,
  2. the response parses as a JSON object (`dict`),
  3. `daily_limit(body)` is `False` (exact equality check `body.get("error") == "Daily request limit exceeded"` in [`thermowatt_read_only.py`](../../../thermowatt-heater/thermowatt_read_only.py) line 28), and
  4. `body.get("success") is False`.
- Because `body.get("success") is False` is checked **before** `body.get("error")`, and `safe_diagnostic()` intentionally suppresses raw vendor strings to prevent leaking sensitive response content, any non-`Daily request limit exceeded` vendor error text accompanying `success: false` collapses to `cloud_success_false`.
- Because the HTTP status was `2xx` (not `401`/`403`/`429`), `AuthGuard` remained `authorized` (not locked). `tick()` (lines 1724–1764) called `_offline()`, set `failures = 1`, `base = max(1800, 3600) = 3600 s`, persisted the cooldown in `request_usage.json`, and set `cloud_health = "backoff"`.

**Hypotheses (unproven without vendor-side telemetry):**
1. **Most likely:** Transient MyThermowatt/Ariston backend failure or brief heater-to-cloud connectivity gap returning HTTP 200 `{"success": false, ...}`.
2. **Possible:** Alternate vendor quota/throttling/maintenance message whose `error` string does not literally match `"Daily request limit exceeded"`.
3. **Possible (high impact if true):** Stale/expired session rejected on `GET /status` with HTTP 200 `{"success": false}` instead of HTTP `401`. Earlier field observations (`thermowatt_bridge.py:324`) saw HTTP `401` for expired tokens, making this less likely than (1); however, if it occurs in `1.5.0` Smart mode, `ordinary_smart_get` skips proactive 20-minute refresh and `request()` only reactively refreshes on HTTP `401` (verified deterministically in `test_smart_mode_ordinary_get_does_not_proactively_refresh_on_cloud_success_false`). If the ~11:00 PM recovery poll also fails with `cloud_success_false` while the official Thermann app continues to work, this becomes a strong suspect.
4. **Possible:** Concurrent session contention if another client (e.g. official Thermann app) refreshed/rotated credentials around 10:00 PM.

---

### 2. Could current polling and token-refresh frequency contribute to cloud rejection?

**Confirmed behaviour in Bridge `1.5.0`:**
- `cloud_polling: "smart"` (default in `1.5.0`) **reduces** both polling and token-refresh frequency compared with `1.3.13–1.3.17`:
  - Quiet `stable_off` / `stable_baseline`: up to **90 min** daytime (`QUIET_DAY_SECONDS = 5400`) and up to **8 h** overnight (`QUIET_OVERNIGHT_SECONDS = 28800`), woken at known tariff/policy boundaries (`22:00` peak end).
  - Active temperature-relevant periods: 15–30 min (`MIN_INTERVAL = 900`, clock-aligned 30 min slots).
  - Fixed fallback during outages: 30 min (`FIXED_POLL_SECONDS = 1800`, max 48 GETs/day).
  - Ordinary Smart `GET /status` skips proactive 20-minute token refresh (`ordinary_smart_get`, `thermowatt_bridge.py:642–652`); reactive refresh runs at most once on HTTP `401` (guarded by 5-minute `REFRESH_COOLDOWN`).
  - Proactive 20-minute refresh runs only on `command_refresh`, confirmations, discovery, and POSTs (`thermowatt_bridge.py:649, 1548`).
- **Assessment:** Excessive request or token-refresh frequency is **unlikely** to have caused a rate limit during the quiet 17:00–22:00 evening peak. Conversely, Smart mode's *lack* of proactive refresh on ordinary `GET /status` means an aged token is never refreshed on `cloud_success_false` — even during fixed-fallback recovery after `_offline()`, because `ordinary_smart_get` checks `self.smart` rather than `self.poll_schedule.active`.

---

### 3. Are scheduled heating requests retained, retried, and confirmed after cloud recovery?

It depends critically on **which side of the 22:00 boundary** the failure occurred:

| Regime | Sequence at ~22:00 Hobart | State during 3,600 s backoff | Outcome at ~23:00 recovery |
| --- | --- | --- | --- |
| **Regime 1: Clean outage before publish** | Bridge fails and HA sees `cloud_health = backoff` / `availability = offline` *before* controller evaluates at 22:00. | `change_requested`, `intent = None`, `heater = off`. No MQTT command published. | **Automatic recovery.** Fresh `Off` poll clears gates; controller publishes `Manual:45@off`, bridge reuses fresh status (0 extra GETs), POSTs `/manual` (45 °C), confirms at 60 s -> `baseline_45`. |
| **Regime 2a: In-flight poll race (queue silently drained)** | Smart polling schedules a `22:00:00` `GET /status` (`executor.py:408–414`) at the **exact same time** the controller wants `Manual:45@off`. Controller publishes `Manual:45@off` while `GET /status` is in flight; `GET /status` fails with `cloud_success_false`; `_offline()` **silently drains `self.commands`** (`thermowatt_bridge.py:723–727`) without recording `last_command`. | `confirming`, `intent.status = "published"`, `heater = off`, `bridge.last_command` unchanged, `bridge.pending = None`, heater stays Off. | **Locks (`fault_locked`).** Fresh `Off` poll at 23:00 is `>= 7 min` after publish (`late_poll`, `controller.py:825–835`) -> resolves `not_applied` and locks with `fault = "command_not_applied"` (misleadingly saying command "was sent"). |
| **Regime 2b: Backoff-propagation race (command waits 60 min in queue)** | Bridge fails at `22:00:00` and enters backoff; controller publishes `Manual:45@off` before HA ingests `cloud_health = backoff`. `on_mqtt_message` queues the command, but `tick()` returns at `clock < next_cloud` (`thermowatt_bridge.py:1663`) for 60 min without reading `self.commands`. | `confirming`, `intent.status = "published"`, `heater = off`, `bridge.last_command` unchanged, `bridge.pending = None`, heater stays Off. | **Locks (`fault_locked`).** At 23:00, `tick()` pops the 3,600 s old command -> `process_command` drops it as `dropped_command_older_than_30s` (`thermowatt_bridge.py:1425`) -> `controller._confirm()` locks with `fault = "bridge_refused_or_dropped"`. |
| **Regime 2c: Pre-command refresh failure** | Controller publishes `Manual:45@off`; bridge runs `command_status_refresh` which gets `cloud_success_false`. | Bridge records `refused_status_refresh_failed` immediately and enters 3,600 s backoff. | Within 1 minute, controller resolves `not_applied` and locks with `fault = "bridge_refused_or_dropped"`. (Does not remain `published` for an hour.) |

**Live incident match:** The reported symptoms (*"`cloud_success_false` during a status poll ... 3,600-second backoff ... request remained published and unconfirmed ... official Thermann app confirms Off"*) match **Regime 2a or 2b** word for word.

---

### 4. Can an essential heating request remain pending indefinitely or be lost during an outage?

- **Pending indefinitely? No.** Bridge `self.pending` (only created if a POST is attempted) expires at `CONFIRM_DEADLINE = 360 s` even while offline (`_expire_pending`, `thermowatt_bridge.py:1320–1323, 1633`). Controller `self.intent` is bounded by `confirmation_timeout_minutes = 65.0` (`controller.py:836–844`), or resolved earlier on `late_poll` (`>= 7 min`) or `bridge_failure`.
- **Lost (heater left Off overnight without manual action)? Yes — confirmed in Regime 2.** In Regimes 2a, 2b, 2c, or on failure to recover at +1 h (`confirmation_timeout` at +65 min), the controller transitions to `fault_locked` and never automatically retries `Manual:45@off`. The existing `parked_off_cannot_restore` alert fires at +30 min (`controller.py:1046–1077`) to warn the owner.

---

### 5. Will the controller return to normal automatic operation without manual intervention?

- **Bridge `1.5.0`:** **Yes** — assuming the cloud accepts the ~11:00 PM recovery poll, the bridge will automatically clear backoff (`failures = 0`, `cloud_health = "ok"`, `availability = "online"`) and resume normal status updates.
- **Controller `0.18.1`:** **No (for this live incident).** Because `Manual:45@off` is already in `confirming` (`intent.status = "published"`), at ~11:00 PM the controller is predicted to lock into **`fault_locked`** (`command_not_applied` in Regime 2a, `bridge_refused_or_dropped` in Regime 2b, or `confirmation_timeout` at ~11:05 PM if the 11:00 PM poll also fails).
- **Manual recovery path if locked:** Press **Acknowledge fault**; the controller enters `observing`, waits for one fresh status poll (up to 30 min unless refreshed), classifies `Off`, and then automatically applies the current policy target.

---

### 6. Are repeated status failures producing excessive duplicate notifications?

- **During continuous backoff / consecutive failures:** **No duplicate spam of the same alert key.** `Controller._supervise_alerts()` enforces `notification_cooldown_hours = 6.0` (`controller.py:163, 1199–1205`), `persistent_notification` updates in-place by deterministic ID (`thermann_shadow_<key>`), 30-second bridge diagnostics do not trigger controller evaluations (`__init__.py:143` watches only `last_poll`, `grid`, `heater_power`, `pv`), and bridge log warnings deduplicate on `(operation, code, delay)` (`thermowatt_bridge.py:1765`).
- **Two confirmed notification-noise gaps:**
  1. **Cooldown erasure on brief `unavailable` / `ok` flaps (`controller.py:1154, 1206–1209`):** `del self.alerts[key]` removes the cooldown timestamp on any single tick where an alert is absent. Because line 1154 checks `obs.cloud_health not in (None, "ok")`, a 1-minute `unavailable` (`None`) glitch on `sensor.home_cloud_health` resets the 6-hour cooldown and immediately re-notifies `cloud_fault` when `backoff` returns (verified in `test_notifications_no_spam_on_backoff_but_unavailable_gap_resets_cooldown`).
  2. **Multi-alert cascade for one outage:** A single 1-hour outage at a heating transition can emit up to **4 distinct notifications** (4 push notifications if `controller_notify_service` is configured): `cloud_fault` (T+0m) -> `parked_off_cannot_restore` (T+30m) -> `status_stale` (T+35..65m) -> `fault_*` (T+60..65m).

---

### 7. Proposed recovery safeguard improvements (SEPARATE — NOT YET APPLIED; OWNER APPROVAL REQUIRED)

None of the fixes below modify heating policies (`45/62/70 °C`, peak-OFF, solar boost) or weaken `AuthGuard`, exact-prior checks, or zero-retry POST safety. Per `AGENTS.md`, items touching bridge/controller retry, fallback, or token refresh require explicit owner approval before implementation.

1. **Bridge — Report explicit refusals instead of silently draining or queuing commands in backoff** *(approval required: command handling; 0 extra cloud requests)*
   - In `thermowatt_bridge.py:_offline()` (lines 723–727): when draining `self.commands`, record `_command_result(kind, payload, "refused_cloud_backoff")` (or `"dropped_bridge_offline"` if MQTT/cloud is disabled) instead of silently discarding commands.
   - In `thermowatt_bridge.py:tick()` (before line 1663 `if self.clock() < self.next_cloud: return`): immediately drain any newly queued command during backoff/auth-lock with `_command_result(..., "refused_cloud_backoff")` / `"refused_auth_not_ready"` (making zero HTTP requests) instead of leaving it queued for 60 minutes until `dropped_command_older_than_30s`.

2. **Controller — Defer back to `change_requested` (not `fault_locked`) on proven-never-sent transient backoff refusals** *(approval required: automatic fallback behaviour; 0 extra cloud requests)*
   - In `controller.py:_confirm()` (lines 788–795): when `bridge_fresh` reports a proven-never-sent transient backoff refusal (`refused_cloud_backoff`, or `refused_status_refresh_failed` with a non-auth/non-quota error and `obs.bridge_confirmation_pending is False`), resolve the intent as `"deferred_cloud_backoff"` (keeping it in `history` and `commands` so it can never loop) and return the controller to `CHANGE_REQUESTED` with `self.heater` intact instead of `FAULT_LOCKED`.
   - Keep `FAULT_LOCKED` unconditionally for every uncertain POST (`not_confirmed_within_limit`, `confirmation_timeout`), `command_not_applied`, `rejected_by_cloud`, `refused_auth_not_ready`, and `refused_cloud_quota_limited`.
   - Result: when cloud recovers at +1 h and confirms `Off`, the controller automatically applies `Manual:45@off` without manual intervention.

3. **Executor — Advance pre-transition Smart poll slightly before off-peak/baseline boundaries** *(approval required: polling schedule; 0 extra cloud requests, saves 1 GET on healthy transitions)*
   - In `executor.py:_event_decision_at()` (lines 408–414): schedule off-peak/baseline boundary reads slightly ahead of the transition (e.g., `boundary - 60 s`) rather than identically at `22:00:00`, avoiding the synchronous collision between the bridge's scheduled `GET /status` and the controller's `22:00:00` command evaluation.

4. **Bridge — Safe diagnostic & optional recovery-refresh safeguard for HTTP 200 `success: false`** *(approval required: auth/diagnostics; only if live 11:00 PM recovery fails with `cloud_success_false` while official app works)*
   - Preserve secret redaction; optionally record an allowlisted non-sensitive boolean (`error_present`) or closed vendor error category if safe patterns are verified.
   - Only if evidence shows the vendor returns HTTP 200 `success: false` for stale tokens: allow at most **one** existing `PROACTIVE_REFRESH_AGE` (`>= 20 min`, guarded by `AuthGuard` and 5-min `REFRESH_COOLDOWN`) refresh on a post-failure recovery poll (`self.failures >= 1`), never in a loop and never bypassing `AuthGuard`.

5. **Controller — Preserve notification cooldown across brief `unavailable` / flapping ticks** *(low risk, separate from policy)*
   - Track last-notified timestamps separately from active/resolved persistent-notification keys so a 1-minute `cloud_health = unavailable` gap cannot reset `notification_cooldown_hours` (6 h) and re-send phone push notifications.

---

## Deterministic regression tests added

Added [`tests/test_cloud_outage_recovery.py`](../../../tests/test_cloud_outage_recovery.py) covering:
- Outage (`cloud_success_false`) cleanly before the 22:00 Hobart transition, 3,600 s backoff, and automatic recovery to `baseline_45`.
- Live-incident Race A (in-flight `22:00` status poll failure draining `self.commands`) and Race B (command queued during backoff expiring as `dropped_command_older_than_30s` at 23:00), proving both currently lock into `fault_locked` at 23:00.
- Pre-command `command_status_refresh` failing with `cloud_success_false` -> 3,600 s backoff and `fault_locked` without sending a POST.
- Failure to recover at +1 h -> 7,200 s doubled backoff, automatic recovery at +3 h from `change_requested`, and 65-minute `confirmation_timeout` lock when in `confirming`.
- Notification deduplication during continuous backoff vs cooldown reset on a 1-minute `unavailable` gap.
- Smart-mode `ordinary_smart_get` skipping proactive refresh on both initial and +1 h recovery `cloud_success_false` polls.
