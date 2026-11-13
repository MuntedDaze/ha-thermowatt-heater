# Upgrade 0.6.2 → 0.7.0 (development candidate: review first)

**Not approved for installation.** 0.7.0 is on the feature branch for owner review. Unit tests and closed-loop simulations pass, but the new economic permission, the morning allowance and the guest/holiday modes **have not run on the real heater**.

**What carries over (CI checks this on real HA storage from 0.6.2, the installed version, compared byte for byte with the live files, and from 0.6.1 and 0.6.0):**
- every saved option, unchanged;
- every entity ID and rename;
- the controller state stays disabled;
- nothing is published.

**What is added:**

| Kind | Entities |
| --- | --- |
| Settings | morning preferred time (06:00), morning hard time (07:00), morning preferred reserve (45 °C) |
| Buttons | Start guest mode (12 h), Cancel guest mode, Cancel holiday mode |
| Datetimes | Holiday departure, Holiday return |
| Sensors | Hot water operating mode, Guest mode ends, Tank thermal state (estimate) |

**Changed meaning:**
- The morning goal is now 06:00/07:00 every day, no longer the weekday morning peak start.
- The three legacy morning/shower settings keep their values but no longer affect control; they are hidden from the settings dashboard.

**Steps (when approved):**
1. Check the package checksum (`Get-FileHash <zip> -Algorithm SHA256`), unzip it, and confirm `manifest.json` says 0.7.0.
2. Delete `\<your-HA-host>\config\custom_components	hermann_shadow`. Don't remove the integration in Home Assistant.
3. Copy in the package's `thermann_shadow` folder.
4. Restart Home Assistant once.
5. Check the log for `thermann_shadow` errors.
6. Check:
   - *Automatic heater control* is **off**;
   - the state is `disabled`;
   - the operating mode is `disabled`;
   - the three new morning settings show 06:00, 07:00 and 45 °C.

**Rollback:** delete the folder, copy in the 0.6.2 package (`thermann_shadow-0.6.2-5fe48e3.zip`), restart once.

## Physical verification needed before enabling

1. **Stage C supervised trial** with 0.7.0. Watch:
   - standby permission after thermostat satisfaction;
   - pre-peak decisions on sunny and cloudy days;
   - command counts per day.
2. **Morning:** record the readings at 06:00 and 07:00 for a week, to check the 0.5 °C/h + 1 °C allowance.
3. **Guest mode:** one start/cancel cycle with the owner present.
4. **Holiday mode:** first a short "holiday" (for example 26 h) while home, before relying on it.
5. Let the thermal observer collect evidence during all of the above (THERMAL_MODEL.md).
