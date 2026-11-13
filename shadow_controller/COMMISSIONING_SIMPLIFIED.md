# Commissioning the simplified controller (0.9.1 + app 1.3.13)

**Nothing here has been done.** Every step that changes the owner's Home
Assistant, the app or the heater needs the owner's explicit approval at the
time. Merging a PR never authorises installation, cloud requests or heater
operation (AGENTS.md).

| Component | Installed now | This release | PR |
| --- | --- | --- | --- |
| Thermann Hot Water app (bridge) | 1.3.11 | **1.3.13** | #25 |
| Thermann Controller integration | 0.7.1 (automatic control off since 12 Nov 20:13) | **0.9.1** (0.9.0 plus the audit corrections; build the package from the head that carries it) | #26, audit fixes |
| Policy and strategy | – | simplified three-state policy | #24 |

The design is in [SIMPLIFIED_STRATEGY.md](SIMPLIFIED_STRATEGY.md).

## Packages (built from the PR heads; `dist/`, not committed)

| Package | Built from |
| --- | --- |
| `thermann_shadow-0.9.0-<head>.zip` (controller, dashboard, this runbook) | the final #26 head |
| `thermann-hot-water-1.3.13-<head>.zip` (app source, for reference; the app itself comes from the store) | the final #26 head (app identical to #25) |
| `thermann_shadow-0.7.1-9ca7ea5-rollback.zip` (the installed controller) | `9ca7ea5` (#22) |
| `thermann-hot-water-1.3.11-9b86e84-rollback.zip` (the installed app source) | `main` `9b86e84` |

The hashes are in `dist/SHA256SUMS-commissioning-<head>.txt`. Rebuild the
0.9.0 package from `main` after stage 1, and check it is identical.

**How each part is installed:**
- The **app** is installed from this GitHub repository in the app store, so
  1.3.13 is installed **in place**, as an update, once `main` carries it.
- **Never copy the app to the local add-ons share.** A local copy is a
  different app (`local_thermowatt_boiler`) with an empty `/data`. The saved
  authentication state, tokens, request accounting and command state would
  be left behind, and a password login would be needed.
- The **controller** is copied in from its package.

## What must be preserved

| Where | What | How it is kept |
| --- | --- | --- |
| App options | `email`, `password`, `cloud_enabled: true`, `commands_enabled` (currently **true**, from T3c), `command_policy: automation`, `poll_interval_minutes: 30` / `minutes`, `min_cloud_retry_minutes`, `on_demand_refresh_enabled: false`, **`auth_retry_generation`** | Update in place, with no option edits. Never raise `auth_retry_generation`: that forces a password login. |
| App `/data` | `auth_state.json` (guard, tokens), `request_usage.json`, `command_state.json`, `thermowatt_config.json` | Same app ID; 1.3.13 reads the same formats |
| Controller entry | Every saved setting: tariff (Aurora 93, standard clock, rates, feed-in), meter verification and sign (`import_positive: false`), freshness limits, command topic, notification service, budgets. Also the planner settings retired in 0.9.0, kept for a rollback. | Folder replacement only; never remove the integration |
| Sensor mappings | Heater, vendor mode, last poll, cloud health and request counter; GoodWe grid, PV, house and AC output; the **EMHASS PV and load forecast** sensors | The same entry; check they are present |
| Controller storage | `.storage/thermann_shadow.<entry>.controller`: enabled **false**, owner modes; `…thermal` | Loaded by 0.9.0; an old pending intent is never re-sent |
| Entity IDs | All measurement, tariff, controller, owner-mode and settings entities | Unchanged. Removed: the planner sensors, the retired settings' controls and the two holiday datetimes (replaced by date entities). |

**Needed by 0.9.1:**
- *Use published forecasts* is on, with the EMHASS sensors mapped. Automatic
  control cannot be turned on without it (0.9.1), and it is locked while
  control is on;
- the meter is verified and its sign is correct;
- the tariff is verified.

## 0. Preflight (owner actions; nothing is installed)

1. Automatic control is **off** (since 12 Nov 20:13). Keep it off until stage 7.
2. **Settings → System → Backups:** create a **full** backup, which includes
   the app and its `/data` and `/config`.
3. **Settings → Apps → Thermann Hot Water → Info:** note the version (1.3.11)
   and the repository it comes from (`MuntedDaze/ha-thermowatt-heater`).
   **Configuration → ⋮ → Edit in YAML:** copy the options, without the
   password.
4. **Thermann Controller → Configure:** note the sensor mappings, *Use
   published forecasts*, and the System page (command topic, budgets).
5. Note the current heater state in the Thermann app. Nothing automatic changes
   it until stage 7.

## 1. Put 1.3.13 and 0.9.0 on `main` (approval: merge)

The app store installs from `main`, so the reviewed stack must be merged
before the app can be updated. Merging installs nothing.

1. Fold the stack top-down, keeping every PR as its own record:
   #26 → #25's branch, then #25 → #24, and so on down to #21 → #20's branch.
2. Squash-merge #20 into `main` as one commit, *Thermann Hot Water 1.3.13 +
   Thermann Controller 0.9.0 (consolidates #20–#26)*, after CI passes on that
   final head.
3. Check `main`: app `version: "1.3.13"`, controller manifest `0.9.0`, and
   the bridge and controller files identical to the commissioning packages.

## 2. Update the app to 1.3.13, in place (approval: app update)

1. **Settings → Apps → Thermann Hot Water:** **Check for updates**, then
   **Update**. Tick *Create backup before updating*; that backup is the app
   rollback.
2. Do **not** change any option.
3. Run the read-only checks in
   [UPGRADING_1_3_13.md](../docs/history/bridge/UPGRADING_1_3_13.md):
   - the session is reused, with no `password_login`;
   - `cloud_health: ok`;
   - polls arrive at :00 and :30, each as `token_refresh` + `status`;
   - diagnostics show `command_transitions` and `poll_schedule: clock_aligned`.
4. **Pass:** about 4 requests an hour, no 401s, no lock.
   **Stop and roll back** on any `auth_locked` or repeated `backoff`.

The installed controller 0.7.1 still works with 1.3.13 (it uses the 1.3.11
`Manual:70` and `off` forms), but it stays off.

## 3. Install controller 0.9.0 (approval: integration installation)

1. Delete `/config/custom_components/thermann_shadow`, copy the 0.9.0 folder in,
   and restart Home Assistant once. Do not remove the integration.
2. Check, read-only:
   - no `thermann_shadow` errors in the log;
   - automatic control is still **off**;
   - *Three-state commands qualified (1.3.13)* is **off**;
   - the controller state is `disabled`;
   - the planner sensors are gone (removed from the registry, not left
     "unavailable"); every other entity ID is unchanged;
   - saved settings are unchanged; the retired ones keep their values;
   - Configure shows *Tariff and forecast settings*, *System and
     commissioning* and *Sensor mappings*;
   - the EMHASS forecast sensors are mapped and *Use published forecasts* is
     on (*Forecast age* below 35 min, *Forecast net surplus* shown).
3. Replace the dashboard with the new `shadow_controller/dashboard.yaml`.

## 4. Shadow observation (no approval needed beyond stage 3; at least 2 weekdays and 1 weekend)

With automatic control off, the policy runs every minute on the observed heater
state and records the command it **would** send. Nothing is published.
**Shadow command** shows the latest one; the controller sensor's
`policy_plan.shadow_log` keeps the last 30.

Check against the agreed design:

| When | Expected shadow behaviour |
| --- | --- |
| Weekday 07:58 (summer) / 06:58 (winter) | `off@<state>`: the park, 2 minutes before the morning peak |
| Weekday after the morning peak | `Manual:70@off` at the **Hypothetical heating start** (the cheapest window, often later when EMHASS shows sun), at the latest by the **Latest continuous heating start** |
| Weekday 16:58 / 15:58 | `off@70`, unless 3.3 kW of measured surplus has held for 10 minutes |
| Weekday 22:00 / 21:00 | `Manual:45@off` |
| Weekend | Manual 45; `Manual:70@45` only with at least 1 kW measured surplus that EMHASS does not beat later |

Because the heater does not follow in shadow mode:

- the same wish is recorded once a day until it changes (0.9.1; each day's park
  appears);
- every payload names the state the heater is **observed** in. With the heater
  left in Manual 45 °C, expect `off@45` at the parks and `Manual:70@45` for the
  start, and no `Manual:45@off` at 22:00 (it is already there).

Note anything unexpected; that is the point of this stage.

## 5. App option for activation and restart reads (approval: app option change; optional)

`on_demand_refresh_enabled: true` lets the controller ask for ONE guarded
status read when automatic control is turned on and after a Home Assistant
restart. That costs about 2 requests each time and avoids waiting up to 30
minutes for the first decision. All the bridge's spacing (5 min),
authentication, backoff and quota gates still apply. Without it, the request
is ignored and the next :00/:30 poll is used.

## 6. Supervised qualification of the three-state commands (approval: heater operation; owner present)

Use **Developer tools → Actions → `mqtt.publish`** with topic
`P/<serial>/CMD/MODE`, QoS 1, not retained. Before each test, confirm the
starting state in the Thermann app. Allow 6 minutes after each command
(confirmation reads at 60 s and 300 s), and at least 15 minutes between
commands. Record the app display, diagnostics `last_command` and the request
count.

| # | Start state | Payload | Expected |
| --- | --- | --- | --- |
| Q1 | OFF | `Manual:45@off` | App: Manual 45 °C. `observed_in_status`. 2 requests (3 if the status was over 60 s old). |
| Q2 | Manual 45 | `Manual:70@45` | Manual 70 °C. `observed_in_status`. |
| Q3 | Manual 70 | `Manual:45@70` | Manual 45 °C. `observed_in_status`. |
| Q4 | Manual 45 | `off@45` | OFF. `observed_in_status`. |
| Q5 | OFF | `Manual:70@off` | Manual 70 °C. `observed_in_status`. |
| Q6 | Manual 70 | `off@70` | OFF. `observed_in_status`. |
| Q7 | Set Manual 55 in the app | `off@70` | `refused_target_mismatch`, **no POST**, heater unchanged |
| Q8 | OFF | `Manual:70@off`, sent twice within 6 min | The second is `refused_confirmation_pending`, with no request |

**Pass:** every app result matches; the first read after each POST is at
about 60 s; nothing is repeated; no 401 or lock. Then turn on *Three-state
commands qualified (1.3.13)* (automatic control must be off).

## 7. First automatic operation (approval: enable automatic control; owner watching)

1. With automatic control off, set *Controller command topic* to the topic the
   bridge announced (`P/<serial>/CMD/MODE`).
2. Choose a weekday, and enable **after** the 07:58 park time, so the first
   decision is a daytime one. The controller re-inspects the heater from a
   NEW status first (stage 5 makes that immediate).
3. Watch the first command, its confirmation, the 16:58 park and the 22:00
   Manual 45. Each appears in *Last command* / *Last command result*, and in
   the Thermann app.
4. To stop at any time:
   - **Hold** pauses all commands;
   - turning automatic control **off** stops it;
   - a change made in the app always pauses control until **Resume**.

## Rollback

| What | How | Notes |
| --- | --- | --- |
| Stop control | Automatic control **off** (or Hold) | Immediate; the heater stays in its current state |
| Controller → 0.7.1 | Replace the folder with the `custom_components/thermann_shadow` folder from `thermann_shadow-0.7.1-9ca7ea5-rollback.zip`, then restart HA | The settings and entry are read as before; 0.9.0's retired settings were never removed. 0.7.1 ignores the new `controller_three_state_qualified` option and re-inspects the heater (its stored state names do not cover 0.9.0's, so it starts by observing). Turn control off first. |
| App → 1.3.11 | **Settings → System → Backups**: restore the app from the backup made before the update (it restores the app and its `/data` together) | An older app refuses the six new payloads (`refused_by_policy`), so roll the controller back first, or keep it off. The 1.3.11 source package is for reference. The restored `/data` holds the tokens from before the update, and 1.3.13 has refreshed them since. If the cloud no longer accepts the old refresh token, 1.3.11 locks (`auth_http_4xx`) and needs one `auth_retry_generation` increase and a password login; that is expected, not a new fault. |
| Heater | Thermann app | Choose OFF, Manual 45 °C or Manual 70 °C yourself |

Never reset an authentication lock automatically; see the app documentation.
