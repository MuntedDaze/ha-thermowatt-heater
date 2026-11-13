# Thermann Controller (`thermann_shadow`)

*Unofficial community software, not a Thermann product.*

A Home Assistant integration that decides which of three settings a Thermann
Smart Electric heater uses, so hot water is ready and costs as little as
practical:

- **Thermann OFF**;
- **Manual 45 °C**;
- **Manual 70 °C**.

It works through the Thermann Hot Water app (1.3.13 or later). Thermann's own
thermostat still decides when the element actually runs.

Current version: **0.9.0** (in review). Installed: **0.7.1**, automatic
control off. To switch to 0.9.0, follow
[COMMISSIONING_SIMPLIFIED.md](COMMISSIONING_SIMPLIFIED.md).

## What it does

| When | Setting |
| --- | --- |
| Weekday nights after the evening peak, and all weekend | **Manual 45 °C**. The native thermostat looks after showers. |
| Weekday daytime, before the evening peak | **Manual 70 °C**, started in the cheapest window that reaches 70 °C by the soft target (15:30 winter, 16:30 summer). Uses the EMHASS forecast, the measured solar and household load, and the tariff. If waiting would miss the soft target, it starts on off-peak power. Once started, it keeps going until the peak. |
| Every peak (morning and evening), from 2 minutes before | **OFF**, unless measured surplus of at least 3.3 kW has held for 10 minutes. That permission is withdrawn after 5 minutes of grid import (over 0.2 kW), or of too little solar. |
| Weekends with solar | **Manual 70 °C** while at least 1 kW of measured surplus makes it worth it and EMHASS shows nothing cheaper later. A passing cloud does not end it. |

Further rules:

- At least **15 minutes** between commands.
- **No minimum heating or rest periods**: the thermostat switches the element.
- **No extra cloud requests:** decisions use local readings every minute.
- **Never against the heater:** its antibacterial and frost protection run on
  their own in every setting.

**Owner modes:**

| Mode | What happens |
| --- | --- |
| **12hr Override** | Button: Manual 70 °C for 12 hours, regardless of price. Cancel at any time. |
| **Holiday** | Set a **departure date** and a **return date**. Both take effect at **00:00 Hobart time**. Today's departure date starts Holiday mode at once; a later one starts it at 00:00 on that date. The heater is switched OFF through the normal guarded command and stays OFF. At 00:00 on the return date, Holiday mode ends by itself and normal control resumes, so the tank usually reheats overnight on Manual 45 °C. A return date of 14 November ends it at 00:00 on 14 November. There is no return target or pre-heating. |
| **Hold** | Button: pauses all automatic commands until you press Resume. |

**App changes win.** If you change the heater in the Thermann app, control
pauses until you press **Resume automatic control**.

**Shadow observation.** While automatic control is off, the policy still runs
and shows the command it **would** send (*Shadow command*). Nothing is sent.

## Install or upgrade

1. Copy the package's `custom_components/thermann_shadow` folder into
   `/config/custom_components/`. When upgrading, delete the old folder first.
   Do not remove the integration in Home Assistant.
2. Restart Home Assistant once.
3. **First install:** add *Thermann Controller* under Settings → Devices &
   services. Map your entities:
   - heater, vendor mode and bridge diagnostics;
   - GoodWe PV, house and grid;
   - the EMHASS PV and load forecast sensors.

   Turn on *Use published forecasts*.
4. **Check:** no `thermann_shadow` errors in the log, and *Automatic heater
   control* is **off**.

Saved settings and entity IDs are kept across upgrades. 0.9.0 retires the old
planner's sensors and settings: their registry entries are removed, and the
stored setting values are kept for a rollback.

**Before automatic control can be switched on:**

- the app's `commands_enabled` is on, with `command_policy: automation`;
- *Controller command topic* (`P/<serial>/CMD/MODE`) is set;
- *Three-state commands qualified (1.3.13)* is on, after the supervised
  qualification.

## Main entities

| Entity | Shows |
| --- | --- |
| *Automatic heater control* (switch) | Master on/off. Turning it off never changes the heater. |
| *Automatic control state* / *reason* | parked, baseline_45, storage_70, change_requested, confirming, owner override, fault, and why |
| *Policy wanted state*, *Policy mode*, *Decision code* | what the policy wants now (off / baseline / storage) and why |
| *Hypothetical heating start*, *Latest continuous heating start*, *Soft target time* | the plan before the evening peak |
| *Storage target reached* | yes only at a reading of 70 °C (63–69 °C is the thermostat band) |
| *Shadow command* | the payload the policy would send while control is off |
| *Heater element state* + confidence | whether the element is drawing power (from the meter) |
| *Controller fault* | none, or what needs your attention |
| *Tank thermal state (estimate)* | diagnostics only |

## Troubleshooting

| You see | Meaning | What to do |
| --- | --- | --- |
| State `owner_override` | The heater was changed outside the controller, or Hold is on | Check the app. Press **Resume** when it's how you want it. |
| Fault `command_not_confirmed` | A command was sent once but not confirmed | Check the app, set the mode you want, then press **Acknowledge**. |
| Fault `bridge_refused_or_dropped` | The app did not send the command (see the reason) | Fix the cause, then Acknowledge. |
| `bridge_1_3_13_required` | The Thermann Hot Water app is older than 1.3.13 | Update the app. |
| `three_state_commands_not_qualified` | The supervised qualification is not recorded | See COMMISSIONING_SIMPLIFIED.md. |
| `heater_status_too_old`, "heater status missing" | No fresh reading from the app | Check the app log and cloud health. |
| "70 °C may not be reached before the peak" | A big draw or a late start | Nothing to do: it heats on off-peak power until the peak. |

## Recovery

- **Hot water now:** Thermann app → **Manual at 70 °C**.
- **Stop automatic control:** switch *Automatic heater control* off.
- **Roll back:** see the end of COMMISSIONING_SIMPLIFIED.md.

## More

- [SIMPLIFIED_STRATEGY.md](SIMPLIFIED_STRATEGY.md): the agreed design and its simulation results.
- [HOW_IT_DECIDES.md](HOW_IT_DECIDES.md): technical reference.
- [COMMISSIONING_SIMPLIFIED.md](COMMISSIONING_SIMPLIFIED.md): deployment, supervised tests and rollback.
- [FORECAST_SETUP.md](FORECAST_SETUP.md): setting up EMHASS forecasts.
- [CHANGELOG.md](CHANGELOG.md).
- `docs/history/controller/`: earlier designs and references.
