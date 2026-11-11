# Stage A — install the planner and controller (control disabled)

**Not yet approved. Nothing here has been done to your Home Assistant.**
Stage A installs code only. It sends no heater command, changes no Thermann
mode, Schedule, target or T-Comfort, and leaves the Thermowatt add-on at
**1.3.8** with commands disabled. Automatic hot-water control stays **off**, and
it cannot be switched on until Stages B and C are complete.

Your system, from a read-only check on 11 Nov:
- Home Assistant **2026.11.1**;
- `thermann_shadow` **0.3.0** installed;
- Hot Water storage dashboard (`/hot-water`);
- saved morning threshold 40 °C.

CI tests exactly this upgrade, 0.3.0 → 0.5.0 on HA 2026.11.1, over real
persisted storage.

## Install 0.4.0 first, or go straight to 0.5.0?

**Go straight to 0.5.0.** It contains all of 0.4.0, and with control disabled it
behaves as the 0.4.0 planner plus inert controller entities. The direct
0.3.0 → 0.5.0 upgrade is what CI verifies:
- every entity ID, unique ID, rename and option is kept;
- history is kept;
- the only migration is morning threshold 40 → 42 °C.

Installing 0.4.0 first would add a second restart and nothing that is tested.

## What is kept, and what changes

**Kept:**
- the config entry and all saved options;
- every existing `thermann_shadow` entity ID and its recorder history;
- the Thermowatt add-on, its credentials, tokens, guard state and options;
- every other integration, automation and dashboard.

**Changes:**
- **Morning threshold:** a saved 40 °C (the old default) becomes **42 °C**.
- **Weekend morning time:** your saved `07:00` is now read as the weekend morning
  time. You can change it later in Settings; this is optional.
- **Retired sensors:** four now show *unavailable*: simulated cycle count,
  simulated stop count, suppressed switching episodes, simulated session cost.
  Remove them later if you like.
- **New entities:**
  - about 13 controller sensors;
  - the *Automatic heater control* switch (**off**);
  - three owner buttons;
  - the 0.4.0 and 0.5.0 settings.
- **New file:** `.storage/thermann_shadow.<entry_id>.controller`, created on the
  first write after start.

## Steps

### 1. Back up (about 10 minutes)

1. **Full backup:** Settings → System → Backups → **Create backup** → choose a
   full backup (Home Assistant settings and history, plus all add-ons, including
   Thermowatt). Wait until it shows as complete, then use ⋮ → **Download** to
   copy it to your PC.
2. **The current component:** on your PC, open
   `\\<your-HA-host>\config\custom_components\` and **copy** the `thermann_shadow`
   folder to somewhere outside HA, for example
   `Documents\ha-backups\thermann_shadow-0.3.0-<date>\`. Check that the copy
   contains `manifest.json` with `"version": "0.3.0"`.
3. **The dashboard:** open the Hot Water dashboard → ✏️ Edit → ⋮ → **Raw
   configuration editor**. Select all, copy, and save it as
   `hot_water_dashboard_0.3.0.yaml` next to the folder copy. Close without saving.
4. **Baseline notes** (keep these private):
   - Thermowatt add-on version **1.3.8**; its Configuration (`commands_enabled:
     false`, `on_demand_refresh_enabled: false`, 30-min polling);
   - the *Cloud request attempts* value and its `request_categories`
     (`command: 0`);
   - in the Thermann app: mode **Schedule**, target **70 °C**, the weekly windows
     (screenshot each day) and **T-Comfort 10 °C**.

### 2. Get the exact package

Use the package built from the reviewed commit (see *Package identity* below).
Unzip it on your PC. It contains `custom_components/thermann_shadow/`
(manifest 0.5.0) and `dashboard.yaml`. Check that the folder includes at least:
- `__init__.py`, `manifest.json`;
- `controller.py`, `control_plan.py`, `executor.py`;
- `advisor.py`, `goals.py`, `heater_state.py`, `strategy.py`;
- `translations/en.json`, `strings.json`.

### 3. Replace only this component's folder

1. In `\\<your-HA-host>\config\custom_components\`, **delete** the `thermann_shadow`
   folder; your copy from step 1.2 is the backup. Do **not** rename it inside
   `custom_components`: Home Assistant would try to load the renamed folder as
   another integration.
2. Copy the new `thermann_shadow` folder into `custom_components\`.
3. Open the copied `manifest.json` and confirm `"version": "0.5.0"`. There must be
   no `__pycache__` folder (the package has none).

Do not touch anything else in `/config`. Do not remove or re-add the integration
in the HA UI.

### 4. Restart Home Assistant once

Settings → System → ⋮ (top right) → **Restart Home Assistant** → *Restart Home
Assistant*. Restart HA only, not the host. Wait until the UI is back (1–3
minutes).

Then check Settings → System → **Logs** and filter `thermann_shadow`: there
should be no errors. A warning about a custom integration not tested by Home
Assistant is normal.

### 5. Update the Hot Water dashboard

Hot Water dashboard → ✏️ Edit → ⋮ → **Raw configuration editor** → replace
everything with the package's `dashboard.yaml` → **Save**. Change only this
dashboard.

### 6. Verify the controller is present but completely disabled

| Check | Expected |
| --- | --- |
| `switch.thermann_shadow_automatic_heater_control` | **off**; attribute `commissioning_missing` lists 3 items (topic, empty-Schedule confirmation, T3 qualification) |
| `sensor.thermann_shadow_automatic_control_state` | **disabled**; reason `automatic_control_disabled` |
| `sensor.thermann_shadow_controller` attributes | `control_capable: false`, `controller_active: false`, `shadow_mode: true` |
| *Commands in last 24 hours* / *Last command* | `0` / unknown |
| Settings → Controller group | *Controller command topic* blank; *Empty Schedule park confirmed* **off**; *Bridge commands qualified (T3)* **off** |
| HA notifications | none from the controller |

**Optional safety check.** Try to switch *Automatic heater control* on. It must
refuse ("cannot be enabled until commissioning is complete …") and stay off.
Nothing is sent. Leave the Hold, Resume and Acknowledge buttons alone; they are
harmless, but there is nothing for them to do yet.

### 7. Verify the bridge, app and native Schedule are unaffected

| Check | Expected |
| --- | --- |
| Thermowatt add-on | still **1.3.8**, running, Configuration unchanged |
| *Last successful poll* | advances about every 30 minutes |
| *Cloud health* | `ok`; auth `authorized` |
| *Cloud request attempts* | rises about 6 per hour, as before; `command: 0`, `confirmation: 0` |
| Thermann app | Schedule, 70 °C, same weekly windows, T-Comfort 10 °C |
| Next native window (for example 04:00 or 11:00 on a weekday) | the element starts as before: about +3 kW at the meter, and *Heater element state* ON |
| Planner | *Recommendation* is no longer stuck on DATA UNAVAILABLE (the 0.4.0 fix); readiness and deadlines show |

Observe for **24–48 hours** before asking to start Stage B.

## Rollback (any time)

1. **Component:** delete `custom_components\thermann_shadow` and copy back your
   0.3.0 folder from step 1.2. Restart Home Assistant once.
2. **Dashboard:** paste `hot_water_dashboard_0.3.0.yaml` back into the Raw
   configuration editor.
3. **Leftovers:** optionally delete `\\<your-HA-host>\config\.storage\thermann_shadow.*.controller`.
   The new controller entities then show *unavailable*; remove them under
   Settings → Entities if you like. The 42 °C threshold stays (set it to 40 if
   you prefer). The entry loads in 0.3.0, because the minor version is
   unchanged within major version 1.
4. **Only if Home Assistant itself misbehaves:** restore the step 1.1 backup
   (Settings → System → Backups → the backup → Restore). Restoring the full
   backup also rewinds history to the backup time.

No heater handback is ever needed: Stage A sends nothing to the heater.

## Package identity

The package is built from the reviewed `codex/controller-0.5.0` branch (PR #13);
see the PR comment for the exact commit, zip name and SHA-256.
`git archive` of `custom_components/thermann_shadow` at that commit reproduces
the folder exactly.
