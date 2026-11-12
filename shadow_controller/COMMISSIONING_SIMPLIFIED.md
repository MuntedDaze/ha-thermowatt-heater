# Commissioning the simplified controller (0.9.0 + app 1.3.13)

**Nothing here has been done.** Every step that changes the owner's Home
Assistant, the app or the heater needs the owner's explicit approval at the
time. Merging a PR never authorises installation, cloud requests or heater
operation (AGENTS.md).

| Component | Installed now | This release | PR |
| --- | --- | --- | --- |
| Thermann Hot Water app (bridge) | 1.3.11 | **1.3.13** | #25 |
| Thermann Controller integration | 0.7.1 (automatic control off since 12 Nov 20:13) | **0.9.0** | #26 |
| Policy and strategy | – | simplified three-state policy | #24 |

The design is in [SIMPLIFIED_STRATEGY.md](SIMPLIFIED_STRATEGY.md).

## 0. Before starting

1. Automatic control is **off** (it has been since 12 Nov 20:13). Keep it off
   until step 6.
2. Take a Home Assistant backup that includes both the app and `/config`.
3. Note the current heater state in the Thermann app. During steps 1–5 the heater
   stays exactly as you leave it; nothing automatic changes it.
4. Build the rollback packages before installing, so they are at hand:

   ```bash
   git -c core.autocrlf=false archive --format=zip -o dist/thermann_shadow-0.7.1-9ca7ea5.zip 9ca7ea5 custom_components/thermann_shadow
   ```

## 1. Install app 1.3.13 (approval: app installation)

1. Copy the `thermowatt-heater` folder to the local add-ons share. Then in
   **Settings → Apps → Thermann Hot Water → Update**, read the release notes
   and update. The update is manual (listed in `breaking_versions`).
2. Do **not** change any option. In particular `commands_enabled`,
   `command_policy: automation`, `poll_interval_minutes: 30` and
   `auth_retry_generation` stay as they are.
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

## 2. Install controller 0.9.0 (approval: integration installation)

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

## 3. Shadow observation (no approval needed beyond step 2; at least 2 weekdays and 1 weekend)

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

Because the heater does not follow in shadow mode, the same wish is recorded
only once until it changes. Note anything unexpected; that is the point of this
stage.

## 4. App option for activation and restart reads (approval: app option change; optional)

`on_demand_refresh_enabled: true` lets the controller ask for ONE guarded
status read when automatic control is turned on and after a Home Assistant
restart. That costs about 2 requests each time and avoids waiting up to 30
minutes for the first decision. All the bridge's spacing (5 min),
authentication, backoff and quota gates still apply. Without it, the request
is ignored and the next :00/:30 poll is used.

## 5. Supervised qualification of the three-state commands (approval: heater operation; owner present)

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

## 6. First automatic operation (approval: enable automatic control; owner watching)

1. With automatic control off, set *Controller command topic* to the topic the
   bridge announced (`P/<serial>/CMD/MODE`).
2. Choose a weekday, and enable **after** the 07:58 park time, so the first
   decision is a daytime one. The controller re-inspects the heater from a
   NEW status first (step 4 makes that immediate).
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
| Controller → 0.7.1 | Replace the folder with the 0.7.1 package, restart HA | The settings and entry are read as before; 0.9.0's retired settings were never removed. 0.7.1 ignores the new `controller_three_state_qualified` option and re-inspects the heater (its stored state names do not cover 0.9.0's, so it starts by observing). Turn control off first. |
| App → 1.3.12 / 1.3.11 | Reinstall that version | Same `/data` files. An older app refuses the six new payloads (`refused_by_policy`), so roll the controller back first, or keep it off. |
| Heater | Thermann app | Choose OFF, Manual 45 °C or Manual 70 °C yourself |

Never reset an authentication lock automatically; see the app documentation.
