# Upgrading to Controller 0.18.3 (Thermann Hot Water 1.5.1 unchanged)

For the owner's installation (Home Assistant OS, Thermann Hot Water app 1.5.1,
Controller 0.18.2 or earlier, CT-free GoodWe, EMHASS, fixed-AEST Aurora 93), to
Controller 0.18.3. Thermann Hot Water app stays at **1.5.1** (no app update is
required if already running 1.5.1). These steps are for the owner after review
and approval; they are not permission for an agent to deploy, restart or
operate anything. The earlier 0.16 / 1.4 guide is in
[history](../history/next-major/OWNER_UPGRADE_0_16.md).

What changes is listed in the [controller changelog](../../shadow_controller/CHANGELOG.md)
and [app changelog](../../thermowatt-heater/CHANGELOG.md);
the requirements are in [OPERATING_POLICY.md](../OPERATING_POLICY.md).
Controller 0.18.3 works with app 1.4.1, 1.5.0 and 1.5.1 (installing both
0.18.3 and 1.5.1 enables full boundary-race backoff deferral plus fault-lifecycle
and command-audit fixes).

## 1. Before you start

1. **Settings → System → Backups:** create a full backup including Home
   Assistant and the Thermann Hot Water app data. Download it.
2. **Check the solar start headroom (decision D3).** Controller 0.18.x uses
   0.3 kW above element power (3.3 kW). (Owner check, 20 Nov 2026: the installed
   value is 0.3, so nothing changes.) If a saved configuration stored a
   different `export_headroom_kw`, 0.18.x keeps that value instead so solar
   qualification cannot change silently. To see the saved value now, open the
   file `/config/.storage/core.config_entries` (read-only, for example with the
   File editor app), find the `thermann_shadow` entry and look for
   `"export_headroom_kw"` in its `options`. Absent or `0.3` means nothing changes.
   Do not edit the file.
3. Note whether any of your own dashboards or automations use these entities,
   which 0.18.x removes (the shipped dashboards do not): the Legacy-page
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
- **Configure → Diagnostic report** (or Download diagnostics) shows, under
  `preferences`, `solar_start_headroom_kw: 0.3` and
  `solar_start_headroom_basis: agreed_constant`, unless
  your installed value was kept.
- The sensor `sensor.thermann_shadow_morning_hot_water_availability` keeps its
  ID and is now shown as *Low hot water before evening peak*.
- **Polling:** the controller follows the app. If the app's polling option is
  Smart, *Actual adaptive polling status* reads `adaptive:…` within a few
  minutes; otherwise the app keeps its fixed 30-minute schedule.
- **Persisted `0.18.2` fault recovery (if upgrading with a retained `command_not_applied` fault):**
  - If **Automatic heater control** is OFF, the controller loads in `disabled`
    with `Controller fault` still showing `command_not_applied`. If Automatic
    control was ON, 0.18.3 safely locks into `fault_locked` on startup and sends
    no commands until you acknowledge.
  - Check the official Thermann app first to confirm the heater's current mode
    matches what you expect.
  - Press **Acknowledge controller fault** (on the Home Control **System** tab,
    the Thermowatt dashboard, or **Settings → Devices & services → Thermann
    Controller**). Acknowledgement records `last_acknowledged_fault` /
    `last_acknowledged_at`, clears the active fault, never retries an uncertain
    command, and waits for a fresh status poll before acting.
- Turn **Automatic heater control** back on only when you intend to (separate
  decision).

## 4. Update the Thermann Hot Water app to 1.5.1 (if not already on 1.5.1)

Skip this section if Thermann Hot Water is already running **1.5.1** (no bridge
code changed for Controller 0.18.3). Otherwise, do this after the controller is
running 0.18.3 (keep **Automatic heater control** off until supervised
commissioning).

1. With **Automatic heater control** off, check there is no pending command
   (*Last command result* is not `awaiting_confirmation`).
2. **Settings → Apps → Thermann Hot Water → Update.** Supervisor asks first
   because 1.5.1 is marked as a breaking version. Do not uninstall, reinstall
   or delete the app's data: credentials, tokens, authentication generation,
   guard state, request ledger and command journal stay in place.
3. Open the app's **Configuration** tab. The only polling option is
   **Cloud polling: smart**. The old polling mode, interval and adaptive
   options are gone; a saved custom interval no longer applies (the fixed
   schedule is 30 minutes). Leave `commands_enabled`, `command_policy`,
   `cloud_enabled` and `auth_retry_generation` exactly as they were.
4. Start the app. Its log shows `Poll interval=1800 seconds`. Within a few
   minutes the controller's *Actual adaptive polling status* reads `adaptive:…`
   (Smart plans accepted), or `fixed_fallback` until the first fresh reading.
5. Turn **Automatic heater control** back on only when you intend to.

## 5. Roll back if needed

Preferred: restore the backup from step 1 (it restores the app and its data
too). For the app alone, restore its partial backup taken before the update;
1.4.1 then starts with its old option defaults (polling mode *existing*, fixed
30-minute polling) unless you re-enter your previous options. Alternatively,
for the controller, reinstall Controller
0.17.1's files and restart: it loads the migrated entry (same major version).
The retired values stay in `retired_options`, which 0.17.1 ignores, so it uses
its old defaults for them; in particular its own polling choice returns to
*Keep existing* (fixed polling) until you select Smart again there.

## 6. Supervised commissioning checklist (before Automatic is turned on)

Run with the owner present, in a quiet off-peak period. Each step only reads
state unless it says otherwise.

1. **Configuration intact:** tariff prices and peak times, fixed AEST clock,
   time zone, grid sign (`import_positive` off for export-positive GoodWe),
   CT-free record, command topic and *Four-state commands qualified* are as
   they were before the upgrade. *Settings* shows no Legacy page.
2. **Bridge healthy:** *Cloud health* `ok`, authentication `authorized`,
   commands enabled as before, request budget with headroom.
3. **Policy view in Shadow (Automatic still off):** *Requested mode* and
   *Current heating plan* match the policy for the time of day — Manual 45
   overnight, OFF in a peak, Manual 62 planned on a weekday before the evening
   peak. No morning top-up is planned.
4. **Forecast independence:** the diagnostic report's `forecast` section shows
   whether EMHASS is in use. If it is unavailable, the plan still shows the
   weekday latest start and the weekend deadline; no action is needed.
5. **Owner turns Automatic on** (separate approval). Watch the first command:
   *Last command result* reaches `observed_in_status` and the Thermann app shows
   the same target.
6. **Owner change test:** change the mode in the Thermann app; the controller
   shows *owner override* and sends nothing until **Resume automatic control**.
7. Leave it running and review the next weekday peak transition (OFF at about
   07:58 / 16:58 Hobart summer time) and the following 62 storage.
