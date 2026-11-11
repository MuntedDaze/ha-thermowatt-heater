# Upgrading 0.3.0 → 0.4.0 (owner steps; not yet authorised)

**For a later, separately approved deployment.** Nothing here has been run on
your Home Assistant. 0.4.0 stays read-only: it never operates, reprograms or
re-authenticates the heater, and it adds no Thermann requests.

## Never change

- Thermowatt add-on **1.3.8**: credentials, tokens, guard state, options, MQTT
  IDs, 30-min polling, commands and on-demand refresh disabled.
- Native **Schedule**, the 70 °C native target, power state and **T-Comfort 10 °C**.
- EMHASS configuration, the EMHASS forecast automation and Tapo routines (Stage 3a
  does not need any change to them).

## Upgrade

1. **Back up** HA (Settings → System → Backups). Copy
   `/config/custom_components/thermann_shadow` and your dashboard YAML aside.
   Record the commit you install.
2. Replace **only** `/config/custom_components/thermann_shadow` with this
   version's folder. `manifest.json` must say `0.4.0`. New files: `advisor.py`,
   `goals.py`, `heater_state.py`, `strategy.py`. Do not delete the integration.
3. **Restart HA Core once.**
4. What happens automatically (proven in isolated CI by real 0.3.0 → 0.4.0 and
   0.2.0 → 0.4.0 upgrades over persisted HA storage):
   - all existing entity IDs, unique IDs, renames and history are kept;
   - every saved option is kept, **except** one documented migration: a saved
     morning threshold of exactly **40 °C** (the old default) becomes **42 °C**.
     Any other value you chose is kept. The config entry becomes version 1.2;
   - new options take defaults when absent: weekend morning 08:00, weekend
     afternoon 16:00, optional shower time off (07:00), expected morning use 10 °C,
     standing loss 0.2 °C/h, waiting threshold $0.05/kWh, AC limit 5 kW, household
     load basis `measured_only`;
   - **four retired sensors** stop updating: *Simulated cycle count, Simulated
     stop count, Suppressed switching episodes, Simulated session cost*. Remove
     them under Settings → Entities (filter `thermann_shadow`, status
     *Unavailable*) if you like.
5. **Note your saved weekend morning time:** 0.3.0 saved `07:00`, which 0.4.0
   reads as the **weekend** morning ready time. Change it to 08:00 (the new
   default) on the Settings view if you prefer.
6. Replace the dashboard with `shadow_controller/dashboard.yaml` (Raw configuration
   editor). Native cards only. If you renamed `thermann_shadow` entity IDs, edit
   those references.

## Verify (all local)

1. Diagnostics: `control_capable: false`, extra cloud requests 0.
2. The recommendation is available most of the time, including when the heater
   status has not changed for over 45 minutes. This is the main fix.
3. **Heater element state** shows ON during native Schedule heating (e.g. after
   11:00 on a weekday) with the basis `WaterHeaterSts_bit0_set` /
   `house_load_consistent_with_element`, and OFF otherwise. **Base household load**
   should be about 0.6–1 kW, not 3–4 kW, while the element runs.
4. **Morning/afternoon ready deadline** show 08:00 / 17:00 on summer weekdays
   (07:00 / 16:00 in winter) and your household times on weekends.
5. **Next tariff change** and its period match your Aurora bill.
6. Change a harmless preference and back; nothing is sent to the heater.

## Rollback

Restore the 0.3.0 folder and dashboard, restart HA Core once. The entry (minor
version 1.2) still loads in 0.3.0: HA accepts a higher minor version within
the same major version. The 42 °C threshold remains (valid in 0.3.0; set 40 if
you want the old behaviour). The 0.4.0-only option keys are ignored by 0.3.0,
and the new 0.4.0 sensors become unavailable (remove them if you like). No
heater handback is needed in either direction.
