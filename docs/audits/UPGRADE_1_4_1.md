# In-place upgrade: bridge 1.4.0 → 1.4.1, controller 0.16.0 → 0.16.1

This is for an installation that already runs released controller 0.16.0 and
bridge 1.4.0 (main `e8de03f`). It is a maintenance update and needs no new
settings. These instructions are for the owner **after** PR #43 has been
reviewed, approved and merged. They do not authorise an agent to deploy.

What changes:

- **Bridge 1.4.1** (needed): Smart plans whose poll time Home Assistant shows
  to the whole second are accepted. A reconnect or cloud error no longer keeps
  a discarded Smart deadline. Diagnostics add rejection categories and
  on-demand refresh outcomes.
- **Controller 0.16.1** (optional): the copyable diagnostic report shows the
  actual polling mode, plan counts, rejection categories and refresh outcomes.
  Control behaviour is unchanged.

What does not change: the App identity `thermowatt_boiler`, options, cloud and
command flags, credentials, the auth store and `auth_retry_generation`, guards,
the command journal, accounting, the `poll_state.json` journal format, MQTT
discovery and entity IDs, the controller config entry, entity registry, saved
settings, Hold/Holiday/override state and pending intent. No storage is migrated.
1.4.1 is not listed as a breaking version.

## 1. Before you start

1. Create a full backup in **Settings → System → Backups** that includes HA
   configuration and the Thermann Hot Water App's data. Download it.
2. Copy the current diagnostic report (Thermowatt dashboard → Diagnostics →
   Copy diagnostic report) and keep it privately. Note the bridge
   *Configuration* values. Do not share options that contain credentials.
3. Pick a quiet off-peak time with no command pending (the report shows
   "requested" equal to "confirmed").
4. Optional but conservative: turn **Automatic heater control** OFF. Do not
   clear Hold, Holiday, overrides or guard state.

## 2. Update the bridge in place

1. **Settings → Apps → App store → ⋮ → Check for updates** (older HA calls
   Apps Add-ons).
2. Open the existing **Thermann Hot Water** App and confirm it offers **1.4.1**
   with the 1.4.1 changelog.
3. Press **Update**. Do not uninstall, rebuild from a different repository, add
   a second copy or delete its data. Supervisor keeps `/data` and the options.
4. When it restarts, open the **Log** tab. Expect a normal start, discovery and
   one status read. It respects any persisted cooldown, so it may wait.
5. Open **Configuration** and confirm that every option still has its previous
   value. In particular, check `polling_mode`, `on_demand_refresh_enabled`, the
   cloud and command flags, `auth_retry_generation` and the interval. Change
   nothing because of the update.

## 3. Update the controller (optional)

1. Using your usual file-access method, copy the reviewed
   `custom_components/thermann_shadow/` files over
   `/config/custom_components/thermann_shadow/`. `manifest.json` must be
   directly in that folder. Do not touch `.storage`.
2. **Developer tools → YAML → Check configuration**, then restart Home
   Assistant once.
3. **Settings → Devices & services → Thermann Controller**: one entry, same
   entities and history, and the report shows controller `0.16.1`.

If you skip this step, 0.16.0 keeps working with bridge 1.4.1. Its report
does not know bridge `1.4.1`, so it shows the bridge version as
`unreported`. That is cosmetic.

## 4. Verify

With Smart selected in both the App and the controller:

1. Wait for the next scheduled status read (at most 30 minutes).
2. Copy the diagnostic report. Expect `versions.bridge` 1.4.1 and, under
   `polling`, `actual_mode: adaptive` and `plans_accepted` above zero. On controller
   0.16.0, check the bridge sensor's `adaptive_polling` attribute in
   **Developer tools → States** instead.
3. If plans are still rejected, `rejection_reasons_since_bridge_start` and
   `last_rejection` name the category. Keep the report and do not change
   authentication settings.

## 5. Re-enable automatic control

If you turned it off, turn **Automatic heater control** back on. If you have
changed the heater in the Thermann app in the last couple of minutes, wait one
to two minutes first, because the vendor cloud can lag behind the app (see the
[settle-window follow-up](FOLLOW_UP_CLOUD_SETTLE_WINDOW.md)). Expect
`observing` until the next fresh read, then the normal state.

## Roll back

Restore the backup taken in step 1 (App and HA configuration), or reinstall
the 1.4.0 App from that backup. Bridge 1.4.0 reads the unchanged
`poll_state.json`, and Smart plans will again be rejected but safely bounded by
the 30-minute fallback. Controller 0.16.0 files can be copied back the same way.
