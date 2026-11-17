# Post-release audit: controller 0.16.0 / bridge 1.4.0 (main `e8de03f`)

Audit date 2026-11-17/18. Basis: released `main` at
`e8de03fd49783fa240113acd75f15923dffc4bc1`, examined in an isolated worktree
(branch `codex/smart-plan-acceptance-1.4.1`). Evidence types are kept apart:

- **Code review**: reading the released source.
- **Simulation**: the repository's real bridge worker and controller with
  mocked MQTT, mocked cloud and synthetic clocks. No live service was used.
- **Owner evidence**: the diagnostics the owner reported (23:03 on 17 Nov:
  0 accepted / 7 rejected; later 0 accepted / 38 rejected after fresh reads).

No production Home Assistant, credentials, cloud API or heater was touched.

## 1. Smart polling: root cause (confirmed)

Home Assistant renders the state of a `device_class: timestamp` sensor with
`isoformat(timespec="seconds")` (`homeassistant/components/sensor/entity.py`).
The bridge publishes `last_successful_poll` with microseconds, but the
controller reads the *state* of `sensor.home_last_successful_poll`, so its
`status_at` is `floor(read time)`. The bridge's `AdaptiveSchedule.accept`
required `abs(status_at - read_wall_time) <= 0.01`. The bridge read time comes
from `time.time()`, so it carries a sub-second part. The difference is between
0 and 1 s, and above 0.01 s about 99% of the time. **Every genuine plan was
rejected** and the bridge stayed in `fixed_fallback`, whatever was configured.

Why the tests missed it: the test clock starts at an integer (`1_728_000_000`),
and the plans echoed `bridge.last_success` directly instead of the HA-rendered
state. The published seasonal Smart evidence (`docs/next-major/`) was generated
under the same assumption, so it describes behaviour production never reached.

Reproduction: `tests/test_smart_plan_acceptance_1_4_1.py`. Run against the
released source, the end-to-end, worker and validator tests fail with
`fixed_fallback` / rejection. On the fix branch they pass.

**The next fresh poll will not recover on released code.** Each new read has
a new random sub-second part. Recovery needs bridge 1.4.1.

### Fix (bridge 1.4.1)

- A plan's `status_at` identifies the current read when it is the exact echo
  (as before) **or** exactly `floor(read time)`. The whole-second match is
  refused when another read of the same heater fell in the same wall second
  (`second_ambiguous`). The previous second, a later second, a non-integer
  near-miss and earlier observations are all still rejected.
- Deadlines remain anchored to the bridge's own monotonic read time, shifted
  by the sub-second offset so they land where the controller intended. They
  are **never later**. Lease (180 s), minimum interval, owner-check limits,
  freshness and the 30-minute fallback are unchanged.
- No controller update is needed for the core fix. Controller 0.16.0 plans are
  accepted by bridge 1.4.1.

## 2. Latent defect exposed by the fix (confirmed, fixed)

Once plans are accepted, a quiet plan (up to 8 h) is copied into
`next_background`/`next_poll`. `_offline()` (MQTT reconnect, any cloud error)
cleared the schedule records but **not** those copied deadlines, and
`_adaptive_sync` returns early until rediscovery. After an MQTT reconnect the
heater could therefore stay `unavailable`, and the controller could not act,
until the discarded quiet deadline (up to 8 h). On released code this never
showed because no plan was ever accepted.

Fix: `_restore_fixed_bound()` caps every copied deadline at the next fixed
clock-aligned slot, and never earlier than `usage.cooldown_until` (`next_cloud`
still enforces backoff independently).

## 3. Automatic-control activation (Priority B)

`observing` with `waiting_for_new_heater_status`, then
`heater_state_not_controlled`, is **normal and transitional**. The controller
needs a status read newer than the moment it was enabled. In simulation of the
owner's timeline (enable at 23:03, Manual 45 °C), the controller stays in
`observing` until the next scheduled read and classifies `baseline_45` one
minute later. In production that read was at about 23:27.
`heater_state_not_controlled` is the policy's reason while the controller's
own heater state is still unknown. It is not a fault.

The activation refresh was not served. Two possible causes:

1. `on_demand_refresh_enabled` is `false`. This is the bridge default, and the
   request is then ignored.
2. The last read was under 300 s earlier (`DEMAND_MIN_SPACING`), and the
   request is dropped by design (no queued retry).

Released diagnostics cannot tell these apart. Bridge 1.4.1 records
`on_demand_refresh_activity.outcomes` (`refused_disabled`,
`refused_min_spacing`, `queued`, `accepted_for_read`, ...).

### Finding: an immediate post-Resume read can capture the cloud's stale state (not changed)

I prototyped two controller speed-ups: a refresh request on Resume/acknowledge,
and a 900 s Smart observation while inspecting. The existing failure replay
(`tests/test_pre_review_failure_replay.py`) rejected them. In that replay the
owner sets the heater Off in the app and presses Resume. The immediate read
returned the vendor cloud's lagging Manual 55 °C (you measured a 2–63 s
readback delay in T3c). The controller classified an unexpected target and
re-entered owner override, which paused automatic control for the rest of the
week (about 18 kWh of unserved draw). Both prototypes were **removed**.
Controller 0.16.1 is diagnostics-only.

The same mechanism exists today for **activation**. If the heater is changed in
the app less than about a minute before automatic control is enabled, and the
activation refresh is served, the read can capture the stale state and pause
control in owner override (fail-safe: no commands, but no heating until the
next Resume). A safe fix is a settle window: ignore reads taken less than
about 90 s after a re-inspection began. That changes control logic, needs
owner approval, and is recommended as a separate change.

## 4. Event matrix: refresh after intentional changes

| Event | Fresh status needed | Current behaviour (1.4.1 / 0.16.1) |
|---|---|---|
| Automatic control ON | yes (inspect) | one guarded refresh request; served only if on-demand is enabled and the last read was 300 s or more earlier; otherwise the next scheduled read |
| OFF then ON | yes | same; repeated toggles cannot exceed the 300 s spacing; outcomes visible |
| HA restart | yes (restart re-inspect) | one guarded request on load |
| Bridge App restart | yes | immediate discovery and read (respects persisted cooldown) |
| MQTT reconnect | yes (bridge marks unavailable) | **fixed**: at most the next fixed slot (was up to a discarded 8 h quiet deadline once plans worked); opt-in single guarded read after 300 s spacing |
| Cloud timeout / auth backoff | recovering read is itself fresh | unchanged backoff schedule |
| Polling mode change | bridge option means App restart; controller option means reload | covered by restart rows |
| Resume after Hold | yes | next scheduled read (deliberately no immediate read: see finding) |
| Scheduling settings change | bridge option means restart | covered |

No path adds an HTTP client or a scheduler. Refresh requests are a boolean per
heater, and the bridge's 300 s spacing, authentication, accounting, backoff
and quota gates decide. Reconnect flapping leads to at most one read.

## 5. Cloud efficiency and authentication (Priority D)

- In Smart/minimum mode, ordinary status GETs already skip the 20-minute
  proactive token refresh and refresh only on a 401. The high historical
  `token_refresh` count is mostly the legacy heuristic before the upgrade,
  which refreshed before nearly every 30-minute poll. It should fall in
  1.4.0 regardless of plan acceptance. Plan acceptance reduces status GETs
  further: in simulation a quiet Manual-45 night drops from about 12 reads in
  six hours to 4 or fewer.
- Discovery, command pre-reads and confirmations keep proactive preparation by
  design.
- A 401 within 300 s of a refresh blocks the guard (operator action) rather
  than looping. That is conservative and approval-gated. No change was made.
- The historical `cloud_timeout` is consistent with ordinary backoff recovery.
  There is no evidence of a request loop.

## 6. Heating behaviour (Priority C), review only

- Tariff clock `standard` uses fixed AEST (`utcoffset − dst`) across Tasmanian
  daylight saving. Correct.
- With an export-positive grid sensor, import is computed as `−grid`, and the
  report states `grid_sign: export_positive`. Correct for the GoodWe HK1000.
- CT-free mode reports nominal/unverified element state only. No path treats
  it as verified heater power.
- Smart quiet plans are used only when the controller is steady, not on hold,
  has no intent or command, and the decision equals the observed state. Any
  wanted change (weekend PV start, boost, peak withdrawal) is non-quiet and
  advances the read. Exact-prior and confirmation reads stay with the bridge.
- The 45/62/70 °C roles, peak-OFF policy and owner-override handling were not
  changed and showed no defect in the simulated nights.

## 7. Dashboard (Priority E), recommendations only

`homeowner/thermowatt.yaml` references controller entities that exist in the
integration's definitions. The build check passes. It shows the next poll and
interval, but **not** the actual polling state, so "Smart selected, fixed
fallback in force" is invisible. Recommended for a separate dashboard change:

- Add `Actual adaptive polling status` (for example `fixed_fallback:fixed_fallback`
  vs `adaptive:stable_baseline`) to the Diagnostics view, next to Cloud health.
- Show whether on-demand refresh is enabled on the bridge.
- The copyable report (0.16.1) now includes actual mode, plan counts,
  rejection categories and refresh outcomes.

## 8. Owner actions

**Urgent:** none. The heater is safe on the fixed 30-minute fallback, and every
command still checks its exact prior and confirms.

**When convenient (after review and approval):** install bridge 1.4.1. Smart
plans start being accepted at the next read; no settings change is needed.
Controller 0.16.1 is optional (report clarity only).

**Good practice until a settle window exists:** after changing the heater in
the Thermann app, wait a minute or two before enabling automatic control or
pressing Resume.

**Optional:** enable `on_demand_refresh_enabled` on the bridge for faster
activation and reconnect recovery. It still obeys the 300 s spacing and all
guards.

## 9. Progress / resume notes

- Done: root cause, regression tests (15 functions, 18 cases, in
  `tests/test_smart_plan_acceptance_1_4_1.py`), bridge fix and diagnostics,
  controller report diagnostics, versions, changelogs. Two controller prototypes
  were rejected by the existing failure replay and removed (section 3).
- Validation: `python -m pytest`, `ruff check .`, `ruff format --check .`,
  `compileall`, `tools/build_*.py --check`, mypy as in CI.
- Not possible here: native container builds and Supervisor schema (CI only),
  and any live verification.
