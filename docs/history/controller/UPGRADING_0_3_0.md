# Installing or upgrading to Shadow Planner 0.3.0

**Owner-controlled steps for a later, separately approved installation.** None of
this has been run on the owner's Home Assistant. PR #9 is a draft and must stay
unmerged until the owner decides. This is a read-only planner: nothing below
operates, re-programmes or re-authenticates the heater.

## Never change

- The **Thermowatt add-on stays 1.3.8**: credentials, tokens, guard state,
  saved options, MQTT entity IDs, 30-minute polling, 60-minute error cooldown,
  `commands_enabled: false`, on-demand refresh off, authentication generation.
- Native **Schedule**, the 70 °C native target, power state and **T-Comfort 10 °C**.
- Do not reset locks, delete private add-on data, enable commands/refresh or
  restart the heater or add-on for this update.

## Upgrade from the installed 0.2.0 (expected path)

1. **Back up** Home Assistant (Settings → System → Backups). Copy the current
   `/config/custom_components/thermann_shadow` folder and the manual dashboard YAML
   somewhere safe. Record the PR #9 commit you are installing.
2. Replace **only** `/config/custom_components/thermann_shadow` with this version's
   folder. `manifest.json` must sit directly inside it and say `0.3.0`; avoid an
   extra nested repository folder. Include the new files (`button.py`,
   `cycles.py`, `decision.py`, `economics.py`, `forecast.py`, `number.py`,
   `select.py`, `settings.py`, `settings_entity.py`, `switch.py`, `text.py`,
   `time.py`). **Do not** delete or re-add the integration entry.
3. **Restart Home Assistant Core once** (not the add-on or heater).
4. What is preserved automatically (proven by the isolated CI upgrade test, which
   installs the real 0.2.0 component, saves options and an entity rename to HA
   storage, then loads 0.3.0 over the same storage):
   - the config entry, its ID and **every saved option**, unchanged on load;
   - all 35 existing sensor unique IDs and entity IDs, including renamed ones, so
     **history stays attached**;
   - a saved custom weekly tariff table is detected and kept (custom mode), never
     overwritten by Aurora defaults; meter direction/verification and native
     references are kept.

   New entities appear: two sensors (*Decision code*, *Forecast usable solar before
   deadline*), 39 settings controls and two buttons. New preferences take
   their recommended defaults only when absent. No migration rewrites storage.
5. Replace the manual dashboard: **Settings → Dashboards → (your Thermann
   dashboard) → ⋮ → Edit dashboard → ⋮ → Raw configuration editor**, paste
   `shadow_controller/dashboard.yaml`, save. If you renamed any
   `thermann_shadow` entity IDs, edit those references. It uses native cards only;
   no HACS cards are required.
6. Wait for a **new normal bridge poll** after the restart (up to ~30 minutes).
   DATA UNAVAILABLE until then is expected; do not restart repeatedly or enable
   refresh to hurry it.

## Fresh install (if 0.2.0 is not installed)

Copy the folder as in step 2, restart once, then **Settings → Devices & services
→ Add integration → Thermann Shadow Planner**. The entity selectors are
pre-filled with the owner's Thermann/GoodWe entities; no account or credentials
are needed. Continue with step 5.

## Check it (10 minutes, all local)

1. **Diagnostics view:** `control_capable: false`, extra cloud requests `0`,
   cloud health `ok`, poll age < 45 min, signed grid positive when exporting.
2. **Settings view:** confirm current values — morning 40 °C at 07:00, afternoon
   70 °C, allowance 30 min, start qualification 10 min, loss grace 20 min, minimum
   cycle/gap 30 min, solar headroom 0.3 kW, switching benefit AUD 0.10, tariff
   clock *standard*, Aurora 93 prices. Your earlier saved values are shown if
   they differed.
3. Change a harmless preference (e.g. allowance 30 → 31 → 30). The control,
   Configure and the plan agree immediately; nothing is sent to the heater.
4. **Hot Water view** on desktop and phone: recommendation readable, gauge and
   tiles sensible, no "entity not available" cards. Report any card that does not
   render — this has not been seen on the owner's real devices.
5. Leave **Use published forecasts** off until the inputs in
   [Forecast setup](../../../shadow_controller/FORECAST_SETUP.md) are verified. With forecasts off, expect
   mostly WAIT FOR PLANNED WINDOW then GRID FALLBACK on sunny days: see the
   switching-threshold note in that guide.
6. Watch one normal poll cycle: request attempts may grow by the usual
   status/refresh/replay pattern, never with solar updates or dashboard refreshes.

## Restore and undo

**Restore recommended** (dashboard, with confirmation) resets comfort, solar,
cycle and freshness preferences to recommended values. It keeps the tariff
contract, entity mappings, verifications, meter direction, pause state and native
references, and saves the replaced values so **Undo last restore** can put them
back once. Neither button sends anything to the heater.

## Rollback

Restore the saved 0.2.0 folder and dashboard YAML, restart HA Core once. The entry,
entity registry and history are kept; 0.2.0 ignores the extra 0.3.0 option keys.
The new settings entities become orphaned — remove them under **Settings →
Entities** (filter *thermann_shadow*) if wanted. No heater handback is needed in
either direction because the planner never acquires control.

## Not part of this update

No executor, no heater writes, no Schedule/T-Comfort edits, no authentication
changes, no automatic deployment. Physical On/resume and safe Off remain
unqualified; see [control and recovery](CONTROL_AND_RECOVERY.md).
