# Stage A — install Controller 0.5.0 over Shadow Planner 0.3.0 (control disabled)

**Read-only installation, not activation.** Stage A replaces one custom
integration folder and restarts Home Assistant once. It does **not**:
- send any heater command or MQTT heater message;
- change the Thermann mode, Schedule, 70 °C target or T-Comfort;
- touch the Thermowatt add-on, which stays at 1.3.8 with `commands_enabled: false`
  and on-demand refresh disabled;
- change any other integration, automation, dashboard or recorder history.

*Automatic heater control* stays **OFF**, and it cannot be turned on until
commissioning Stages B and C are approved and completed.

## Decisions for this install (owner, 12 Nov 2026)

- **Direct upgrade** from the installed 0.3.0 to 0.5.0. CI tests exactly this path
  on HA 2026.11.1 over real persisted storage.
- **No backup preparation** (owner's choice; reduced rollback accepted).
  Rollback still exists: the installed 0.3.0 was verified, read-only, to be
  **byte-identical to commit `bd95f04`** (22/22 files), so a rollback package is
  provided from git.

## What is kept, and what changes

**Kept:**
- the existing config entry and all saved options;
- every `thermann_shadow` entity ID and its recorder history;
- all other HA configuration.

**Changes:**
- **Morning threshold:** a saved 40 °C (the old default) becomes **42 °C**.
- **Weekend morning time:** the saved `07:00` is now read as the weekend morning
  time.
- **Retired sensors:** four show *unavailable*: simulated cycle count, simulated
  stop count, suppressed switching episodes, simulated session cost.
- **New entities:** controller sensors, the *Automatic heater control* switch
  (**off**), three owner buttons and new settings.
- **New file:** one state file, `.storage/thermann_shadow.<entry_id>.controller`.
  It is written only when the controller state changes.

## Packages

See the PR #13 comment for the exact commit and SHA-256 of each file.
- **Install:** `thermann_shadow-0.5.0-<commit>.zip`, containing
  `custom_components/thermann_shadow/` (0.5.0), `shadow_controller/dashboard.yaml`
  and this guide.
- **Rollback:** `thermann_shadow-0.3.0-bd95f04-rollback.zip`, the exact installed
  0.3.0 component.

## Procedure — one action at a time

Confirm each action's check before moving on. Stop and ask if any check fails.

1. **Verify the package.** On the PC, check the zip's SHA-256 against the PR
   comment: in PowerShell, `Get-FileHash <zip> -Algorithm SHA256`. Unzip it.
   - *Check:* `custom_components\thermann_shadow\manifest.json` says
     `"version": "0.5.0"`, and there is no `__pycache__` folder.
2. **Record the baseline** (read-only, 1 minute):
   - Thermowatt add-on Info shows **1.3.8**;
   - its Configuration shows `commands_enabled: false` and
     `on_demand_refresh_enabled: false`;
   - the Thermann app shows **Schedule**, **70 °C**, your current windows and
     T-Comfort as they are.

   Don't change anything.
3. **Delete the old folder.** In File Explorer, open
   `\\<your-HA-host>\config\custom_components\` and delete the `thermann_shadow`
   folder.
   - Do **not** rename it inside `custom_components`: a renamed copy would be
     loaded as another integration.
   - Do **not** remove the integration in the HA UI.
4. **Copy the new folder.** Copy the package's `thermann_shadow` folder into
   `\\<your-HA-host>\config\custom_components\`.
   - *Check:* `custom_components\thermann_shadow\manifest.json` says `0.5.0`, and
     `controller.py`, `control_plan.py`, `executor.py` and `translations\en.json`
     are present.
5. **Restart Home Assistant once.** Settings → System → ⋮ → **Restart Home
   Assistant** → *Restart Home Assistant* (not a host reboot). Wait 1–3 minutes.
6. **Check the log.** Settings → System → Logs, filter `thermann_shadow`.
   - *Check:* no errors. A "custom integration not tested by Home Assistant"
     warning is normal.
7. **Check the controller is disabled:**

   | Entity | Expected |
   | --- | --- |
   | `switch.thermann_shadow_automatic_heater_control` | **off**; `commissioning_missing` lists 3 items |
   | `sensor.thermann_shadow_automatic_control_state` | **disabled** (reason `automatic_control_disabled`) |
   | `sensor.thermann_shadow_controller` attributes | `control_capable: false`, `controller_active: false` |
   | `sensor.thermann_shadow_commands_in_last_24_hours` | `0` |
   | Notifications | none from the controller |

   Leave the switch off. Don't press Hold, Resume or Acknowledge.
8. **Check the planner.**
   - *Recommendation* shows a real decision within a few minutes, not stuck on
     DATA UNAVAILABLE.
   - The morning threshold reads 42 °C.
   - *Device clock check* is `check_required`. This is correct while your
     current, non-empty Schedule is active, and it becomes
     `not_applicable_empty_schedule` after Stage C.
9. **Check the bridge and heater are unaffected:**
   - *Last successful poll* keeps advancing about every 30 min, and cloud health
     is `ok`;
   - the request attempts rise about 6 per hour with `command: 0`;
   - the Thermann app is unchanged;
   - the next native window heats as usual: about +3 kW at the meter and
     *Heater element state* ON.
10. **Update the Hot Water dashboard.** Do this only after checks 6–9 pass. Open
    the Hot Water dashboard → ✏️ Edit → ⋮ → **Raw configuration editor**, replace
    the contents with the package's `shadow_controller/dashboard.yaml`, and
    **Save**.
    - *Check:* the new *Automatic control* section shows DISABLED and lists the
      commissioning still needed.

Then observe for **24–48 hours** before Stage B.

## Rollback

1. Delete `custom_components\thermann_shadow`, then copy in the `thermann_shadow`
   folder from the rollback zip (0.3.0, `bd95f04`). Restart HA once.
2. The 0.5.0 dashboard then shows a few unavailable entities. The previous
   dashboard was not exported (owner's choice); the 0.3.0 repository version is
   included in the rollback zip as `shadow_controller/dashboard.yaml`.
3. Optionally delete `.storage\thermann_shadow.*.controller`, and remove the new
   unavailable entities under Settings → Entities.
4. The config entry still loads in 0.3.0 (same major version). The 42 °C
   threshold remains; set it to 40 °C if you want the old value.

No heater handback is needed: Stage A never sends anything to the heater.
