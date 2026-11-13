# Commissioning the simplified controller (controller 0.9.1 + app 1.3.13)

**Nothing here has been done.** Every step that changes the owner's Home
Assistant, the app or the heater needs the owner's explicit approval at the
time. Merging a PR never authorises installation, cloud requests or heater
operation (AGENTS.md).

## Where things stand

| Component | Installed now | To install | Where it comes from |
| --- | --- | --- | --- |
| Thermann Hot Water app (bridge) | 1.3.11 | **1.3.13** | Already on `main` (`04a8d3d`, PRs #20–#26). No later change. |
| Thermann Controller integration | 0.7.1 (automatic control off since 12 Nov 20:13) | **0.9.1** | PR #27, once merged to `main`. |

**Controller 0.9.0 is never installed.** It is on `main` but was superseded by
0.9.1 before installation (the audit corrections in PR #27). Do not use any
`thermann_shadow-0.9.0-*.zip` package.

The design is in [SIMPLIFIED_STRATEGY.md](SIMPLIFIED_STRATEGY.md).

## Order of work

| Stage | What | Approval needed |
| --- | --- | --- |
| 0 | Preflight and backup | – |
| 1 | Merge PR #27, then build the 0.9.1 package from `main` | Merge |
| 2 | Update the app 1.3.11 → 1.3.13, in place | App update |
| 3 | Install controller 0.9.1 (replacing 0.7.1) | Integration installation |
| 4 | Shadow observation: at least 2 weekdays and 1 weekend | – |
| 5 | Optional app option for activation and restart reads | App option change |
| 6 | Supervised qualification of the three-state commands | Heater operation, owner present |
| 7 | Enable automatic control | Enable, owner watching |

Stage 2 does not depend on stage 1 (1.3.13 is already on `main`), but do them
in this order so only one thing changes at a time. Automatic control stays
**off** from now until stage 7.

## Packages

All are in `dist/` (not committed).

| Package | Use | Built from |
| --- | --- | --- |
| `thermann_shadow-0.9.1-<main>.zip` | **Install** (stage 3): the controller, the dashboard, this guide | `main` after PR #27 is merged (stage 1) |
| `thermann_shadow-0.7.1-9ca7ea5-rollback.zip` | **Controller rollback**: the installed 0.7.1 | `9ca7ea5` |
| `thermann-hot-water-1.3.13-04a8d3d.zip` | Reference only: the app's source. The app itself is installed from the app store. | `04a8d3d` |
| `thermann-hot-water-1.3.11-9b86e84-rollback.zip` | Reference only: the installed app's source. The app is rolled back from a backup. | `9b86e84` |

`<main>` is the first seven characters of the `main` commit the package is
built from. The hashes are in `dist/SHA256SUMS-commissioning-<main>.txt`.

A package named `thermann_shadow-0.9.1-<PR head>.zip` is a **review build**
from the PR branch. Install the one built from `main`.

**How each part is installed:**
- The **app** is installed from this GitHub repository in the app store, so
  1.3.13 is installed **in place**, as an update.
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
| Controller entry | Every saved setting: tariff (Aurora 93, standard clock, rates, feed-in), meter verification and sign (`import_positive: false`), freshness limits, command topic, notification service, budgets. Also the planner settings retired since 0.9.0, kept for a rollback. | Folder replacement only; never remove the integration |
| Sensor mappings | Heater, vendor mode, last poll, cloud health and request counter; GoodWe grid, PV, house and AC output; the **EMHASS PV and load forecast** sensors | The same entry; check they are present |
| Controller storage | `.storage/thermann_shadow.<entry>.controller`: enabled **false**, owner modes; `…thermal` | Loaded by 0.9.1; an old pending intent is never re-sent |
| Entity IDs | All measurement, tariff, controller, owner-mode and settings entities | Unchanged. Removed: the planner sensors, the retired settings' controls and the two holiday datetimes (replaced by date entities). |

**Required by 0.9.1 before automatic control can be turned on:**
- *Use published forecasts* is on, with the EMHASS PV and load sensors mapped.
  It is locked while control is on, and *Restore recommended preferences*
  does not change it;
- the command topic is set;
- *Three-state commands qualified (1.3.13)* is on (stage 6).

Also confirm that the meter is verified with the correct sign and that the
tariff is verified.

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

## 1. Merge PR #27 and build the package (approval: merge)

Merging installs nothing.

1. PR #27 is a draft that changes heater-command behaviour, so it needs the
   owner's explicit approval. Check that every CI check passes on its final
   head, mark it ready and squash-merge it into `main`.
2. Check `main`:
   - `custom_components/thermann_shadow/manifest.json` says `"version": "0.9.1"`;
   - `thermowatt-heater/config.yaml` says `version: "1.3.13"`;
   - `thermowatt-heater/` is unchanged from `04a8d3d`
     (`git diff 04a8d3d main -- thermowatt-heater` prints nothing).
3. Build the install package from `main` (replace `<main>` with the first seven
   characters of `git rev-parse main`):

   ```bash
   git archive --format=zip -o dist/thermann_shadow-0.9.1-<main>.zip main custom_components/thermann_shadow shadow_controller/CHANGELOG.md shadow_controller/COMMISSIONING_SIMPLIFIED.md shadow_controller/SIMPLIFIED_STRATEGY.md shadow_controller/dashboard.yaml
   ```

4. Record its SHA-256 in `dist/SHA256SUMS-commissioning-<main>.txt`, with the
   three unchanged packages above. The `custom_components/thermann_shadow`
   folder inside it must be identical to the reviewed PR #27 head.

## 2. Update the app to 1.3.13, in place (approval: app update)

1. Avoid the minute either side of :00 and :30: a token refresh interrupted
   by the restart locks the authentication guard.
2. **Settings → Apps → Thermann Hot Water:** **Check for updates**, then
   **Update**. Tick *Create backup before updating*; that backup is the app
   rollback.
3. Do **not** change any option.
4. Run the read-only checks in
   [UPGRADING_1_3_13.md](../docs/history/bridge/UPGRADING_1_3_13.md):
   - the session is reused, with no `password_login`;
   - `cloud_health: ok`;
   - polls arrive at :00 and :30, each as `token_refresh` + `status`;
   - diagnostics show `command_transitions` and `poll_schedule: clock_aligned`.
5. **Pass:** about 4 requests an hour, no 401s, no lock.
   **Stop and roll back** on any `auth_locked` or repeated `backoff`.

The installed controller 0.7.1 still works with 1.3.13 (it uses the 1.3.11
`Manual:70` and `off` forms), but it stays off.

## 3. Install controller 0.9.1 (approval: integration installation)

This replaces 0.7.1 directly. 0.9.0 is not installed in between.

1. Delete `/config/custom_components/thermann_shadow`, copy in the
   `custom_components/thermann_shadow` folder from
   `thermann_shadow-0.9.1-<main>.zip`, and restart Home Assistant once. Do not
   remove the integration.
2. Check, read-only:
   - **Settings → Devices & services → Thermann Controller** shows version
     0.9.1, with no `thermann_shadow` errors in the log;
   - automatic control is still **off** and the controller state is `disabled`;
   - *Three-state commands qualified (1.3.13)* is **off**;
   - the planner sensors are gone (removed from the registry, not left
     "unavailable"); every other entity ID is unchanged;
   - saved settings are unchanged; the retired ones keep their values;
   - Configure shows *Tariff and forecast settings*, *System and
     commissioning* and *Sensor mappings*;
   - the EMHASS forecast sensors are mapped and *Use published forecasts* is
     on (*Forecast age* below 35 min, *Forecast net surplus* shown). If it is
     off, turn it on now;
   - the *Automatic heater control* switch's `commissioning_missing` attribute
     lists only what is still to do. At this stage that is
     `three_state_commands_not_qualified`, plus
     `command_topic_not_configured` if the topic is not saved.
3. Replace the dashboard with `shadow_controller/dashboard.yaml` from the same
   package.

## 4. Shadow observation (no approval beyond stage 3; at least 2 weekdays and 1 weekend)

With automatic control off, the policy runs every minute on the observed heater
state and records the command it **would** send. Nothing is published.
**Shadow command** shows the latest one; the controller sensor's
`policy_plan.shadow_log` keeps the last 30.

Check against the agreed design. `<state>` is the state the heater is observed
in (`off`, `45` or `70`); see the note under the table.

| When | Expected shadow behaviour |
| --- | --- |
| Weekday 07:58 (summer) / 06:58 (winter) | `off@<state>`: the park, 2 minutes before the morning peak |
| Weekday after the morning peak | `Manual:70@<state>` at the **Hypothetical heating start** (the cheapest window, often later when EMHASS shows sun), at the latest by the **Latest continuous heating start** |
| Weekday 16:58 / 15:58 | `off@<state>`, unless 3.3 kW of measured surplus has held for 10 minutes |
| Weekday 22:00 / 21:00 | `Manual:45@off` (nothing, if the heater is already in Manual 45 °C) |
| Weekend | Manual 45 °C; `Manual:70@45` only with at least 1 kW of measured surplus for 10 minutes that EMHASS does not beat later |

Because the heater does not follow in shadow mode:

- the same wish is recorded once a day until it changes, so each day's park
  appears;
- every payload names the state the heater is **observed** in. With the heater
  left in Manual 45 °C, expect `off@45` at the parks, `Manual:70@45` for the
  start, and no `Manual:45@off` at 22:00.

If the decision is `storage_waiting_no_forecast`, the EMHASS forecast is not
reaching the controller: fix that before stage 7.

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
| Q2 | Manual 45 | `Manual:70@45` | Manual 70 °C. `observed_in_status`. **Also record the element evidence below.** |
| Q3 | Manual 70 | `Manual:45@70` | Manual 45 °C. `observed_in_status`. |
| Q4 | Manual 45 | `off@45` | OFF. `observed_in_status`. |
| Q5 | OFF | `Manual:70@off` | Manual 70 °C. `observed_in_status`. **Also record the element evidence below.** |
| Q6 | Manual 70 | `off@70` | OFF. `observed_in_status`. |
| Q7 | Set Manual 55 in the app | `off@70` | `refused_target_mismatch`, **no POST**, heater unchanged |
| Q8 | OFF | `Manual:70@off`, sent twice within 6 min | The second is `refused_confirmation_pending`, with no request |

### Element evidence for Q2 and Q5

The controller counts the element's 3 kW only in Manual 70 °C, from the
`WaterHeaterSts` status bit and the house-load step. Whether the real status
bit is set at the first read after a start has not been observed. Record it;
change nothing.

Run Q2 and Q5 with the reading **below 62 °C**, so the element actually starts,
and with no large appliance starting or stopping for 10 minutes around the
command.

| When | Record |
| --- | --- |
| Just before the command | Time; `sensor.home_boiler_home_vendor_mode` attribute `WaterHeaterSts` (raw number); GoodWe grid (`sensor.goodwe_inverter_meter_active_power`), house (`sensor.goodwe_inverter_house_consumption`) and PV (`sensor.goodwe_inverter_pv_power`) |
| When the house load steps up by about 3 kW | Time of the step; grid, house and PV after it |
| **At the first confirmation read (about 60 s after the POST)** | Time of *Last successful poll*; the raw `WaterHeaterSts`; grid, house and PV at that moment; *Heater element state* and *Heater state confidence* |
| At the 300 s read, if there is one, and at the next :00/:30 poll | The same values |

**Reading the result:**
- An odd `WaterHeaterSts` (for example 33) at the 60 s read, with the load
  step: the status bit follows the element promptly. Nothing more to do.
- An even value (for example 32) at the 60 s read while the meter shows the
  3 kW step: the bit is delayed. Note when it first turns odd. **Do not go on
  to stage 7**; the estimator is reviewed with these observations first.

**Pass:** every app result matches; the first read after each POST is at
about 60 s; nothing is repeated; no 401 or lock; the Q2 and Q5 element
evidence is recorded and the status bit followed the element. Then turn on
*Three-state commands qualified (1.3.13)* (automatic control must be off).

## 7. First automatic operation (approval: enable automatic control; owner watching)

1. With automatic control off, set *Controller command topic* to the topic the
   bridge announced (`P/<serial>/CMD/MODE`), if it is not already saved.
2. Check the *Automatic heater control* switch: `commissioning_missing` must be
   empty. The switch refuses to turn on while it lists anything
   (`command_topic_not_configured`, `three_state_commands_not_qualified`,
   `published_forecasts_not_enabled`).
3. Choose a weekday, and enable **after** the 07:58 park time, so the first
   decision is a daytime one. The controller re-inspects the heater from a
   NEW status first (stage 5 makes that immediate).
4. Watch the first command, its confirmation, the 16:58 park and the 22:00
   Manual 45 °C. Each appears in *Last command* / *Last command result*, and in
   the Thermann app.
5. To stop at any time:
   - **Hold** pauses all commands;
   - turning automatic control **off** stops it;
   - a change made in the app always pauses control until **Resume**.

## Rollback

Roll back to the versions that are installed today: controller **0.7.1** and
app **1.3.11**. Never roll back to controller 0.9.0.

| What | How | Notes |
| --- | --- | --- |
| Stop control | Automatic control **off** (or Hold) | Immediate; the heater stays in its current state |
| Controller 0.9.1 → 0.7.1 | Turn automatic control off. Replace `/config/custom_components/thermann_shadow` with the folder from `thermann_shadow-0.7.1-9ca7ea5-rollback.zip`, then restart HA. | The settings and entry are read as before; the retired settings were never removed. 0.7.1 ignores the options and stored fields added since, and re-inspects the heater (it starts by observing). |
| App 1.3.13 → 1.3.11 | **Settings → System → Backups**: restore the app from the backup made before the update (it restores the app and its `/data` together) | Roll the controller back first, or keep it off: 1.3.11 refuses the six new payloads (`refused_by_policy`). The restored `/data` holds the tokens from before the update, and 1.3.13 has refreshed them since. If the cloud no longer accepts the old refresh token, 1.3.11 locks (`auth_http_4xx`) and needs one `auth_retry_generation` increase and a password login; that is expected, not a new fault. |
| Heater | Thermann app | Choose OFF, Manual 45 °C or Manual 70 °C yourself |

The two `thermann-hot-water-*.zip` packages are source for reference; the app
is never installed from them.

Never reset an authentication lock automatically; see the app documentation.
