# Upgrade the installed 0.6.1 to 0.6.2 (control stays off)

**Not yet approved; nothing has been done to your Home Assistant.** The upgrade
is code only. It sends no heater command and changes no Thermann mode, target,
Schedule or T-Comfort. *Automatic heater control* stays **off**. The Thermowatt
add-on is a separate update ([UPGRADING_1_3_11.md](../UPGRADING_1_3_11.md)).

**What changes:**
- 0.6.2 needs bridge **1.3.11** to command; until then it reports
  `bridge_1_3_11_required` and sends nothing, even if enabled;
- while the bridge reports a command as `awaiting_confirmation`, the controller
  waits for the bridge's bounded outcome instead of judging a stale read;
- `not_confirmed_within_limit` locks with clear guidance;
  `unexpected_state_after_command` pauses as owner override;
- no command while the bridge awaits any command's outcome.

**Preserved (CI checks this on real HA Core, 0.6.1 → 0.6.2 over persisted
storage, from a copy identical to your installed files):**
- every saved option, unchanged (none added, removed or migrated);
- all entity IDs and renames, with the same set of entities;
- recorder history (the config entry is never removed);
- the persisted controller state, which stays **disabled**;
- nothing is published.

No backup preparation is required. Rollback uses the 0.6.1 package below.

## Order

1. This upgrade (control off). It works with bridge 1.3.10 or 1.3.11.
2. Bridge 1.3.11, after its PR is approved and merged
   ([UPGRADING_1_3_11.md](../UPGRADING_1_3_11.md)).
3. T3c, then the supervised trial ([COMMISSIONING.md](COMMISSIONING.md)).

## Steps

1. **Verify the package.** Check `thermann_shadow-0.6.2-<commit>.zip` against
   the SHA-256 in the PR comment (`Get-FileHash <zip> -Algorithm SHA256`), then
   unzip it. *Check:* `manifest.json` says `"version": "0.6.2"`; no
   `__pycache__`.
2. **Delete** `\\<your-HA-host>\config\custom_components\thermann_shadow`. Do not
   rename it there, and do not remove the integration in HA.
3. **Copy** the package's `thermann_shadow` folder into `custom_components\`.
4. **Restart Home Assistant once** (Settings → System → ⋮ → Restart Home
   Assistant).
5. **Log:** filter `thermann_shadow`; no errors.
6. **Controller off:** *Automatic heater control* **off**, state `disabled`,
   `commissioning_missing` unchanged, commands in 24 h `0`.
7. **Bridge and heater unaffected:** polls continue, cloud `ok`, the app
   unchanged.
8. **Dashboard (optional):** paste the package's `shadow_controller/dashboard.yaml`.

## Rollback

Delete the folder, copy in the 0.6.1 package's `thermann_shadow` folder
(`thermann_shadow-0.6.1-1324a3c.zip`, SHA-256
`57c81033a999edd977a2bd9a8e4f23993a971950a21e8b885f00f5fd489ee29f`), restart once.
No heater handback is needed.
