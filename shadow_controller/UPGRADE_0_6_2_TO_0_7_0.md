# Upgrade 0.6.2 → 0.7.0 (development candidate: review first)

**Not approved for installation.** 0.7.0 is on the feature branch for owner review. Unit tests and closed-loop simulations pass, but the new economic permission, the morning allowance and the guest/holiday modes **have not run on the real heater**.

**What carries over (CI checks this from the installed 0.6.1/0.6.0 over real HA storage):**
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

**Steps (when approved):** the same as UPGRADE_0_6_1_TO_0_6_2.md, using the 0.7.0 package: verify the checksum, replace the folder, restart once, check the log, and confirm the controller is still disabled.

## Physical verification needed before enabling

1. **Stage C supervised trial** with 0.7.0. Watch:
   - standby permission after thermostat satisfaction;
   - pre-peak decisions on sunny and cloudy days;
   - command counts per day.
2. **Morning:** record the readings at 06:00 and 07:00 for a week, to check the 0.5 °C/h + 1 °C allowance.
3. **Guest mode:** one start/cancel cycle with the owner present.
4. **Holiday mode:** first a short "holiday" (for example 26 h) while home, before relying on it.
5. Let the thermal observer collect evidence during all of the above (THERMAL_MODEL.md).
