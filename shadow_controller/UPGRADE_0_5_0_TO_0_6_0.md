# Upgrade the installed 0.5.0 to 0.6.0 (control stays disabled)

**Not yet approved; nothing has been done to your Home Assistant.** The upgrade
is code only. It sends no heater command, changes no Thermann mode, target,
Schedule or T-Comfort, and leaves Thermowatt at **1.3.8** with commands and
on-demand refresh disabled. *Automatic heater control* stays **off**.

**What changes:**
- the parked state is now Thermann **OFF** (the 0.5.0 empty-Schedule park is
  withdrawn);
- the *Empty Schedule park confirmed* setting is removed, so *commissioning
  missing* lists 2 items (topic and T3);
- dashboard texts describe Manual 70 / OFF;
- clock warnings appear only while the native programme is actually in use.

Entity IDs, options, history and the controller state file carry over
unchanged.

## Steps, one action at a time

1. **Verify the package.** Check `thermann_shadow-0.6.0-<commit>.zip` against the
   SHA-256 in the PR #14 comment (`Get-FileHash <zip> -Algorithm SHA256`), then
   unzip it.
   - *Check:* `manifest.json` says `"version": "0.6.0"`; there is no
     `__pycache__`.
2. **Delete the old folder.** Delete `\\<your-HA-host>\config\custom_components\thermann_shadow`.
   Do not rename it there, and do not remove the integration in HA.
3. **Copy the new folder.** Copy the package's `thermann_shadow` folder into
   `custom_components\`.
4. **Restart Home Assistant once.** Settings → System → ⋮ → **Restart Home
   Assistant** (not the host).
5. **Check the log.** Settings → System → Logs, filter `thermann_shadow`.
   - *Check:* no errors.
6. **Check the controller is disabled:**
   - *Automatic heater control* is **off**;
   - *Automatic control state* is `disabled`;
   - `commissioning_missing` lists `command_topic_not_configured` and
     `bridge_commands_not_qualified_t3`;
   - commands in the last 24 h is `0`.
7. **Remove the orphaned setting.** Settings → Entities → filter
   `empty_schedule_park` → the *unavailable* switch → Delete. This is optional.
8. **Check the bridge and heater are unaffected:**
   - polls continue about every 30 min, cloud `ok`, `command: 0`;
   - the app is unchanged;
   - normal heating continues as you have it set today.
9. **Update the Hot Water dashboard.** Raw configuration editor → paste the
   package's `shadow_controller/dashboard.yaml` → Save.

## Rollback

Delete the folder, copy in the 0.5.0 package's `thermann_shadow` folder
(`thermann_shadow-0.5.0-8cc4a4d.zip`, SHA-256
`1bd6eaf53518c20a2c31ddfbf3d4deb958f294b70636ee3d5a678eec6af5ef92`), restart
once, and paste back its `dashboard.yaml`. No heater handback is needed.
