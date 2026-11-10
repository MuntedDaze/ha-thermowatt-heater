# Owner-controlled Shadow Planner 0.2.0 → 0.3.0 update

Do not update Thermowatt: its bridge stays **1.3.8**, including credentials,
tokens, guards, saved options, MQTT IDs, polling and disabled commands/refresh.
PR #9 remains draft; this is a procedure for a later approved installation.

1. Back up HA and download/review the final PR #9 commit. Keep a copy of the
   installed `custom_components/thermann_shadow` folder and manual dashboard.
2. Replace **only** `/config/custom_components/thermann_shadow` with this version's
   folder, including the new local preference entity modules. Do not remove the
   existing integration entry or entity registry. Restart HA once to load files.
3. Existing config-entry data/options are read as before; new options receive
   defaults only when absent. Existing target, meter flags/direction, tariffs,
   native references and mappings are retained. Legacy custom tariff JSON selects
   custom mode automatically rather than being overwritten by Aurora defaults.
   Config-entry version remains 1: no destructive migration is required.
4. Replace the **manual dashboard** definition using `dashboard.yaml`. Existing
   sensor names/unique IDs are unchanged; additional sensors and local settings
   entities are added. HA registry-customised names/suffixes may require updating
   card entity references. History remains attached to existing IDs. No heater
   actions/automations should consume these advisory sensors.
5. Open Settings and check current targets, morning deadline and tariff clock.
   Confirm 70°C afternoon, 40°C threshold, 30-minute allowance, and owner values.
   Leave forecasting off until both timestamped PV and household-load series
   are available. Check optional mappings in Configure using entity selectors.
6. Wait for a new normal Thermowatt poll and fresh local meter reports after
   restart. Check cloud health, poll age, measured signs/units, recommendation
   and explicit simulated-state label. No request rate changes are expected;
   token refresh/replay can still make a polling cycle exceed one HTTP attempt.
7. Change a harmless **local shadow** preference, e.g. allowance 30→31→30.
   Confirm the control, Configure and calculated plan agree without heater or
   cloud action. Reload/restart HA if you want to verify persisted values; the
   session simulation re-qualifies from new data. It never resumes physical heat.
8. Restore recommendations only deliberately using its confirmed dashboard
   action. This restores financial/comfort/cycle defaults but preserves mappings,
   meter verification/direction and native reference settings. Check custom
   tariff intent before confirming an Aurora-default restore.

For rollback, restore the component/dashboard backup and restart HA. Retain the
entry/registry and saved options; 0.2.0 ignores unknown extra keys. It will not
honour newly editable times or Phase 2B cycle/forecast policy, so review old
recommendations accordingly. Neither install nor rollback needs heater handback:
both are shadow-only. No native Schedule/T-Comfort or authentication resets.

Needed from owner before useful forecasting: selected PV/load entity IDs,
example **de-identified forecast attribute shapes**, actual forecast-generation
signal/timestamp, Forecast.Solar panel tilt/azimuth if used, and review of forecast
errors over representative days. No credentials, API responses or live controls
are requested.
