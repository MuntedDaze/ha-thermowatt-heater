# Thermann Controller (`thermann_shadow`)

*Unofficial community software, not a Thermann product.*

A Home Assistant integration that decides **when** a Thermann Smart Electric heater may heat, so hot water is ready when you need it and as cheap as possible. It works through the Thermann Hot Water app and changes only one thing: whether heating is allowed (**Manual at 70 °C**) or parked (**Thermann OFF**). Thermann's own thermostat still decides when the element actually runs.

Current version: **0.7.0** (in review, PR #20). Installed: **0.7.0** since 12 Nov 2026, automatic control off; the supervised trial (Stage C) has not begun. See [COMMISSIONING.md](COMMISSIONING.md).

## What it does

- **Hot water first:**
  - **Every morning:** 45 °C by 06:00 (preferred) and at least 42 °C by 07:00 (hard minimum). If the preferred target is missed, it only makes sure of the minimum.
  - **Afternoon:** as close to 70 °C as is economical before the evening peak.
- **Then cost:**
  - Heating stays allowed while it is cheaper now than the cheapest realistic alternative before the heat is needed. That counts solar (valued at the feed-in rate you give up), off-peak and peak prices (Aurora Tariff 93, fixed AEST), and the forecasts.
  - It parks when heating stops being worth it, including before a peak, unless enough solar makes peak-time heating cheaper than waiting.
- **Then solar and calm operation:**
  - **Solar:** measured from the GoodWe meter, ignoring the heater's own 3 kW, so heating doesn't make it "see" less solar.
  - **Calm switching:** decisions use rolling 10-minute values with sustained-condition timers; at most 6 commands a day (2 kept for comfort); a 30-minute minimum between changes.
- **Never against the heater:**
  - Heating the heater starts itself while OFF (anti-bacterial, frost) is never interrupted.
  - The temperature setting, the Schedule and mains power are never touched.

**Owner modes:**

| Mode | What happens |
| --- | --- |
| **12hr Override** | Button; Manual at 70 °C for 12 hours, regardless of price. Thermann's thermostat still decides when to heat. The end time is shown; cancel at any time. Normal control resumes automatically afterwards. |
| **Holiday** | Set departure and return. The heater stays parked while you're away, and the tank is heated in the cheapest way during the last 24 hours before you return. You are told if heating is blocked or the tank isn't ready when you get back. |
| **Hold** | Button; pauses all automatic commands until you press Resume. |

**App changes win.** If you change the heater in the Thermann app, control pauses until you press **Resume automatic control**.

## Install or upgrade

1. Copy the package's `custom_components/thermann_shadow` folder into `/config/custom_components/`. When upgrading, delete the old folder first. Do not remove the integration in Home Assistant.
2. Restart Home Assistant once.
3. **First install:** add *Thermann Controller* under Settings → Devices & services and map your entities: heater, vendor mode, bridge diagnostics, GoodWe PV / house / grid and, optionally, the EMHASS forecast sensors.
4. **Check:**
   - no `thermann_shadow` errors in the log;
   - *Automatic heater control* is **off**.

Saved settings, entity IDs and history are kept across upgrades. The current upgrade notes are in [UPGRADE_0_6_2_TO_0_7_0.md](UPGRADE_0_6_2_TO_0_7_0.md).

**Before automatic control can be switched on:**
- the bridge's `commands_enabled` is on;
- *Controller command topic* (`P/<serial>/CMD/MODE`) is set;
- *Bridge commands qualified (T3)* is on.

See [COMMISSIONING.md](COMMISSIONING.md).

## Main entities

| Entity | Shows |
| --- | --- |
| *Automatic heater control* (switch) | Master on/off. Turning it off never changes the heater. |
| *Hot water operating mode* | automatic / guest (the 12hr Override) / holiday / disabled |
| *Automatic control state* / *reason* | parked, heating permitted, owner override, fault, … and why |
| *Next heating start* / *stop* | the planned heating times |
| *Morning readiness*, *Afternoon readiness* | whether each goal is on track |
| *Heater element state* + confidence | whether the element is drawing power (from the meter) |
| *Controller fault* | none, or what needs your attention |
| *Tank thermal state (estimate)* | diagnostics only: likely tank condition, suspected water use, heating performance |

Notifications appear in Home Assistant, and optionally on your phone through the *Notification service* setting.

## Troubleshooting

| You see | Meaning | What to do |
| --- | --- | --- |
| State `owner_override` | The heater was changed outside the controller, or Hold is on | Check the app. Press **Resume** when it's how you want it |
| Fault `command_not_confirmed` | A command was sent once but not confirmed | Check the app, set the mode you want, then press **Acknowledge** |
| Fault `bridge_refused_or_dropped` | The bridge didn't send the command (see the reason) | Fix the cause (cloud, commands disabled, …), then Acknowledge |
| `bridge_1_3_11_required` | The bridge add-on is older than 1.3.11 | Update the add-on |
| `heater_status_too_old`, "heater status missing" | No fresh reading from the bridge | Check the add-on log and cloud health |
| "Heating for your return is blocked" | Holiday return heating can't be sent | Check the add-on; select Manual at 70 °C in the app yourself if needed |
| "Protective heating while OFF" | The heater heats on its own (anti-bacterial/frost) | Expected; nothing is interrupted |

## Recovery

- **Hot water now:** Thermann app → **Manual at 70 °C**.
- **Normal programme:** Thermann app → **Schedule**.
- **Stop automatic control:** switch *Automatic heater control* off.
- **Roll back:** delete the folder, copy in the previous package, restart once.

## More

- [HOW_IT_DECIDES.md](HOW_IT_DECIDES.md): technical reference for the decisions, morning rules, modes and outage behaviour.
- [COMMISSIONING.md](COMMISSIONING.md): staged switch-on, with the supervised test results.
- [DASHBOARD_CONTRACT.md](DASHBOARD_CONTRACT.md): entities for the future main dashboard.
- [THERMAL_MODEL.md](THERMAL_MODEL.md): what the thermal observer measures and what's needed before it could ever affect control.
- [FORECAST_SETUP.md](FORECAST_SETUP.md): setting up EMHASS forecasts.
- [CHANGELOG.md](CHANGELOG.md).
- `docs/history/controller/`: design reports, earlier upgrade notes and the full 0.6 reference.
