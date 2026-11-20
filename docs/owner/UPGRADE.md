# Upgrading the existing installation to Controller 0.18.0

For the owner's installation (Home Assistant OS, Thermann Hot Water app 1.4.1,
Controller 0.17.1, CT-free GoodWe, EMHASS, fixed-AEST Aurora 93). These steps
are for the owner after review and approval; they are not permission for an
agent to deploy, restart or operate anything. The earlier 0.16 / 1.4 guide is in
[history](../history/next-major/OWNER_UPGRADE_0_16.md).

What changes is listed in the [controller changelog](../../shadow_controller/CHANGELOG.md);
the requirements are in [OPERATING_POLICY.md](../OPERATING_POLICY.md).
Controller 0.18.0 works with app 1.4.1; the app update is a separate step.

## 1. Before you start

1. **Settings → System → Backups:** create a full backup including Home
   Assistant and the Thermann Hot Water app data. Download it.
2. **Check the solar start headroom (decision D3).** Controller 0.18.0 uses
   0.3 kW above element power (3.3 kW). If your saved configuration ever stored a
   different `export_headroom_kw`, 0.18.0 keeps that value instead so solar
   qualification cannot change silently. To see the saved value now, open the
   file `/config/.storage/core.config_entries` (read-only, for example with the
   File editor app), find the `thermann_shadow` entry and look for
   `"export_headroom_kw"` in its `options`. Absent or `0.3` means nothing changes.
   Do not edit the file.
3. Note whether any of your own dashboards or automations use these entities,
   which 0.18.0 removes (the shipped dashboards do not): the Legacy-page
   settings (adaptive polling, quiet-period checks, app-change check interval,
   polling preview and its two limits, three-state qualification, weekend
   daylight qualification, late-day PV threshold and delay), the controller's
   *Cloud polling mode* select, and the sensors *Shadow next adaptive poll* and
   *Shadow adaptive poll interval*.
4. Turn **Automatic heater control** off. This sends no command; the heater keeps
   its current setting.

## 2. Install the controller files in place

Replace the contents of `/config/custom_components/thermann_shadow/` with the
reviewed commit's `custom_components/thermann_shadow/`. Do not delete the
integration or its configuration entry. Restart Home Assistant.

## 3. Check after the restart

- **Settings → Devices & services → Thermann Controller** loads without error.
- The log shows `0.18.0: N retired settings moved unchanged to retired_options`.
  A warning about the solar start headroom appears only if your stored value
  was not 0.3 kW.
- **Configure → Advanced/System** has no *Legacy and developer settings* page;
  *Data freshness* shows only the two data-age limits.
- **Configure → Diagnostic report** (or Download diagnostics) shows
  `solar_start_headroom` with `basis: agreed_constant` and `kw: 0.3`, unless
  your installed value was kept.
- The sensor `sensor.thermann_shadow_morning_hot_water_availability` keeps its
  ID and is now shown as *Low hot water before evening peak*.
- **Polling:** the controller follows the app. If the app's polling option is
  Smart, *Actual adaptive polling status* reads `adaptive:…` within a few
  minutes; otherwise the app keeps its fixed 30-minute schedule.
- Turn **Automatic heater control** back on only when you intend to (separate
  decision).

## 4. Roll back if needed

Preferred: restore the backup from step 1. Alternatively reinstall Controller
0.17.1's files and restart: it loads the migrated entry (same major version).
The retired values stay in `retired_options`, which 0.17.1 ignores, so it uses
its old defaults for them; in particular its own polling choice returns to
*Keep existing* (fixed polling) until you select Smart again there.
