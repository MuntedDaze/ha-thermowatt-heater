# Upgrade the installed 0.6.0 to 0.6.1 (control stays off)

**Not yet approved; nothing has been done to your Home Assistant.** The upgrade
is code only. It sends no heater command and changes no Thermann mode, target,
Schedule or T-Comfort. *Automatic heater control* stays **off**. The Thermowatt
add-on is a separate update ([UPGRADING_1_3_10.md](../bridge/UPGRADING_1_3_10.md)).

**What changes:**
- 0.6.1 needs bridge **1.3.10** to command (until then it reports
  `bridge_1_3_10_required` and sends nothing, even if enabled);
- no more waiting for a poll slot: with 1.3.10 a command goes when the planner
  decides, and the bridge reads status once first if needed;
- an app change found by the bridge at command time pauses control as owner
  override instead of locking with a fault;
- texts for the latency reserve and command timing.

**Preserved (CI checks this on real HA Core, 0.6.0 → 0.6.1 over persisted
storage):**
- every saved option, unchanged (no option added, removed or migrated);
- all entity IDs and renames (the same entities, none added or removed);
- recorder history, since the config entry is never removed;
- the persisted controller state, which stays **disabled**;
- nothing is published.

No backup preparation is required. Rollback uses the 0.6.0 package below.

## Order

1. This upgrade (controller 0.6.1, control off). Works with bridge 1.3.9 or
   1.3.10.
2. Bridge 1.3.10, after PR #15 is approved and merged
   ([UPGRADING_1_3_10.md](../bridge/UPGRADING_1_3_10.md)).
3. T3b, then the supervised trial ([COMMISSIONING.md](COMMISSIONING_0_6.md)).

## Steps, one action at a time

1. **Verify the package.** Check `thermann_shadow-0.6.1-<commit>.zip` against
   the SHA-256 in the PR comment (`Get-FileHash <zip> -Algorithm SHA256`), then
   unzip it.
   - *Check:* `manifest.json` says `"version": "0.6.1"`; there is no
     `__pycache__`.
2. **Delete the old folder.** Delete
   `\\<your-HA-host>\config\custom_components\thermann_shadow`. Do not rename it
   there, and do not remove the integration in HA.
3. **Copy the new folder.** Copy the package's `thermann_shadow` folder into
   `custom_components\`.
4. **Restart Home Assistant once.** Settings → System → ⋮ → **Restart Home
   Assistant** (not the host).
5. **Check the log.** Settings → System → Logs, filter `thermann_shadow`.
   - *Check:* no errors.
6. **Check the controller is off:**
   - *Automatic heater control* is **off** and *Automatic control state* is
     `disabled`;
   - `commissioning_missing` is unchanged from 0.6.0;
   - commands in the last 24 h is `0`.
7. **Check the bridge and heater are unaffected:** polls continue about every
   30 minutes, cloud `ok`, no new `command` requests, the app unchanged.
8. **Update the Hot Water dashboard.** Raw configuration editor → paste the
   package's `shadow_controller/dashboard.yaml` → Save.

## Rollback

Delete the folder, copy in the 0.6.0 package's `thermann_shadow` folder
(`thermann_shadow-0.6.0-1b5c1c5.zip`, SHA-256
`38380fbf3f58d47e3dca963f9be81eac87a39b7633a0959e90d520c3f1e18dda`), restart
once, and paste back its `dashboard.yaml`. No heater handback is needed.
