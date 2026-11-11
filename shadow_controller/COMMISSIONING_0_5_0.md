# Commissioning runbook — Thermann Hot Water Controller 0.5.0

Every stage needs the owner's **separate, explicit approval** before it starts.
Each has pass/fail criteria and a rollback. Nothing in this runbook has been
performed by the agent.

| Stage | What | Needs |
| --- | --- | --- |
| A | Install the planner (0.4.0, then 0.5.0 with control **off**) | Approval to deploy to HA |
| B | **T3**: prove the bridge's `Manual:70`/`Auto` reproduce the app (T1) results | Approval to merge PR #12 (bridge 1.3.9), update the add-on and enable commands temporarily |
| C | Save the **empty** weekly Schedule; keep a restorable copy | Approval to change the live programme |
| D | Supervised executor trial (limited cycles) | Approval to enable automatic control |
| E | Production enablement | Approval after reviewing D |

**General recovery (any stage).** In the official Thermann app:
- select **Manual** for hot water now (70 °C), or
- select **Schedule** for parked (after Stage C), or the old programme.

In HA, turn **Automatic heater control** off; that never changes the heater
mode. Never reset Thermowatt authentication locks to force anything.

---

## Stage A — install the planner

1. **0.4.0:** follow [UPGRADING_0_4_0.md](UPGRADING_0_4_0.md): backup, replace
   the folder, restart once, verify, roll back if needed.
2. **0.5.0 with control off:**
   - Back up HA again. Replace `/config/custom_components/thermann_shadow` with
     this version (`manifest.json` 0.5.0; new `controller.py`,
     `control_plan.py`, `executor.py`). Restart HA Core once.
   - Import [dashboard.yaml](dashboard.yaml).

**Pass:**
- All existing entity IDs, options and history are kept. New options take
  inert defaults: topic blank, both confirmations off, 6 commands/day,
  220 requests/day, 30-min latency reserve.
- *Automatic heater control* is **off**, and *Automatic control state* is
  `disabled`.
- Turning the switch on fails with "commissioning is complete: …".
- The *controller* sensor's attributes show `control_capable: false`.
- The bridge request counter rises only with its normal polling (about 6 per
  hour).

**Fail / rollback:** restore the 0.4.0 folder (or 0.3.0) and the dashboard,
then restart once. The 0.5.0 controller state file
`.storage/thermann_shadow.<entry>.controller` is ignored by older versions and
may be deleted. No heater handback is needed: nothing was sent.

---

## Stage B — T3 bridge qualification (supervised)

**Preconditions:**
- PR #12 is approved and merged, and the Thermowatt add-on is updated to
  **1.3.9**. It is in `breaking_versions`, so it never updates automatically.
- Credentials, tokens and guard state are unchanged.
- The owner is present, the app works, and the reading is ≤60 °C.
- The test runs outside any native window (or after Stage C), ideally
  off-peak.

1. **Find the command topic.** Settings → Devices & services → MQTT → device
   *Boiler …* → MQTT INFO → the water-heater discovery payload →
   `mode_command_topic` (`P/<serial>/CMD/MODE`). Do not post it publicly.
2. **Enable commands for the test only.** Add-on Configuration:
   `commands_enabled: true`; leave `on_demand_refresh_enabled: false`. Restart
   the add-on. Its diagnostics must show `commands_enabled: true`, cloud health
   `ok` and auth `authorized`.
3. **Record:** request counter, mode (Schedule), target 70, reading, grid power.
4. **Start: `Manual:70`.**
   - Watch *Last successful poll*. **Within 20 s** after it changes, run
     Developer Tools → Actions → `mqtt.publish` with topic = the command topic,
     payload `Manual:70`, retain **off**.
   - **Expect:**
     - bridge `last_command.result` = `observed_in_status` (or
       `not_observed_in_immediate_status`, then Manual at the next poll);
     - mode Manual, target 70;
     - grid import up by about 3 kW within 2 minutes;
     - the app shows Manual 70 with the heating indicator.
   - **Record:** latency from publish to the power step, and the request-count
     increase.
5. Wait at least one poll (30 min) so the background status confirms Manual.
6. **Park: `Auto`.** Same timing, payload `Auto`.
   - **Expect:** `observed_in_status`; mode Schedule, target 70; import down by
     about 3 kW within 2 minutes; the app shows Schedule.
7. **Optional negative check.** Publish `Manual:70` **outside** the 20-second
   slot.
   - **Expect:** `dropped_status_older_than_60s`, no request and no change.
8. Set `commands_enabled: false` again and restart the add-on, unless Stage D
   follows immediately with approval.

**Pass:**
- Both transitions match T1 (about ±3.0 kW, 70 °C kept).
- Confirmation came from observed status.
- The request increase per command is small (expected 2–4).
- No auth lock and no retries.

**Fail:** wrong mode or target, no power step, an auth lock, or an unexpected
refusal. Stop and restore in the app (Schedule or the old programme), set
commands disabled, and report.

**Then, in HA:**
- set *Controller command topic* to the topic;
- switch on *Bridge commands qualified (T3)*;
- record the measured latency and request cost.

---

## Stage C — empty weekly Schedule (persistent park)

The owner has confirmed that a blank Schedule is supported and works. This
stage only records, applies (if not already applied) and verifies it.

1. **Record the current programme.** In the app, screenshot **every day's**
   windows. The last known programme was weekdays 04:00–08:00 and 11:00–17:00,
   weekends 06:00–22:00, T-Comfort 10 °C. Store the screenshots privately; they
   are the restore copy.
2. If the programme is **already empty**, inspect each day and do not rewrite
   it. Otherwise remove all heating times for **every** day and **save** (the
   app requires saving; unsaved changes revert).
3. Keep **T-Comfort 10 °C** and the 70 °C target unchanged.
4. **In HA:**
   - Configure → *Native schedule reference* = `[]`;
   - switch on *Empty Schedule park confirmed*.

**Pass:**
- In Schedule mode, a former window time (e.g. 11:00 on a weekday) passes with
  **no** 3 kW step.
- The controller later reports no `unexplained_heating`, apart from a genuine
  antibacterial or frost cycle.

**Rollback:** re-enter the recorded windows from the screenshots, save, and
switch *Empty Schedule park confirmed* off.

---

## Stage D — supervised executor trial

**Preconditions:** A, B and C have passed. Bridge `commands_enabled: true`. The
owner can watch the dashboard and app for the trial period (suggest 3–7 days,
at most 6 commands/day).

1. Optional: set *Notification service*, for example `mobile_app_<phone>`.
2. Turn on **Automatic heater control**.
   - The state becomes `observing`, then `parked` or `heating_permitted` after
     the next poll.
3. **Review daily: planned versus observed.**

   | Planned | Observed |
   | --- | --- |
   | *Next heating start/stop* and the planner's best plan | *Last command* / *Result* / *Time*; meter steps; *Heater element state* |
   | Readiness | Reading at 08:00 / 17:00 (summer) or 07:00 / 16:00 (winter) |
   | Plan solar share and cost | Meter: element energy on solar versus import |
   | ≤ 6 commands/day | *Commands in last 24 hours*; *Cloud requests in last 24 hours* |

4. **Test the owner controls once each:**
   - press **Hold**: the state becomes `owner_override` and nothing is sent;
     then **Resume**;
   - change the mode in the app once: `owner_override`, and the controller does
     not reverse it.

**Pass:**
- Readiness goals are met, or correctly alerted when unachievable.
- Every command is confirmed, with no `fault_locked` caused by the controller.
- No heating in peak periods without solar, beyond comfort fallbacks.
- No duplicate commands, and the request budget is respected.

**Fail / rollback:** turn the switch off (the heater stays in its current
mode). Set the mode you want in the app. Set bridge `commands_enabled: false`.
If you stop permanently, also revert Stage C.

---

## Stage E — production enablement

After D is reviewed and approved:
- leave automatic control on, and keep notifications;
- keep the conservative defaults: 30-min dwell, 6 commands/day, 220
  requests/day, 30-min latency reserve;
- review weekly for the first month: faults, commands/day, readiness misses,
  cost against the native-Schedule estimate.

Statistical reliability is not assumed until enough operating data exists.

**Rollback:** as in D. Version rollback: as in A. Restore the old programme
from the Stage C screenshots if reverting to native scheduling.

## Owner actions outstanding

1. Approve and perform Stage A (deployment).
2. Approve PR #12, then update the add-on and run T3 (Stage B).
3. Approve and apply or verify the empty Schedule (Stage C).
4. Approve the supervised trial (Stage D), then production (Stage E).
5. Merge decisions for PR #9, #10, #11, #12 and the controller PR.
