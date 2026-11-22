# Unified Home dashboard

A separate, optional dashboard that combines solar/grid/house power flow, weather, hot water, lights, doors
and both bathrooms. It does **not** touch the existing Thermowatt or Tapo dashboards.

Screenshots of the real rendered dashboard (a real Home Assistant frontend, synthetic data) are in
[`screenshots/`](screenshots/): Home at 1920, 1366, 1280 and 390 px (light and dark) and every view at 1920
and 390 px.

## Files and profiles

| File | Purpose |
| --- | --- |
| `homeowner/home_mapping.yaml` | **This household's verified profile** (entity IDs, `battery_present: false`, weather, lights, original bathroom devices, door contacts) |
| `homeowner/generic/home_mapping.yaml` | **Assumption-free defaults** for anyone else: no battery assumed, no weather, no lights, no device names |
| `tools/build_home_dashboard.py` | Generator. `--check` (CI), `--report`, or `--mapping FILE --out-dir DIR` for your own profile |
| `homeowner/home.yaml` | Dashboard (uses `homeowner/www/thermowatt-power-flow-card.js`) |
| `homeowner/home_no_custom_card.yaml` | Same dashboard with a native power-flow fallback |
| `homeowner/home_energy_package.yaml` | Optional package: kW sensors, daily energy, status |
| `homeowner/generic/home.yaml`, `home_energy_package.yaml` | Generic-profile outputs (kept current by CI) |

The committed outputs are generated from the mapping files and checked in CI, so **nothing has to be searched
and replaced by hand and the generator never needs to be run on your Home Assistant**. Verified owner mappings:
GoodWe power and energy entities, `weather.home`, `light.dining_room_light`, `light.living_room_light` (both
dimmable), the original bathroom entities (`sensor.main_temp_humidity`, `sensor.main_temp_temperature`,
`switch.main_fan`, `switch.main_towel_rail`, and the Ensuite equivalents) and the door contacts
`binary_sensor.garage_door` / `binary_sensor.front_door_door`. `status` marks each as `verified` (checked against
this installation's recorder history/registry) or `owner-confirmed` (supplied by the owner).

## Views

| View | Contents |
| --- | --- |
| Home | One screen at 1920x1080: power flow, today's energy, compact hot water + 12 h override, weather, both bathrooms, lights and doors |
| Energy | Power flow, today's figures, retroactive statistics, raw meters, 24 h power history |
| Hot water | Same summary, one override control, one hold/resume control, plan and diagnostics, tank history |
| Bathrooms | Both bathroom cards plus charts of humidity and temperature **and the physical fan and towel relays** (original sensors, so history is not limited to the v0.3.x install date) |
| Doors | Garage and front door **monitoring only**, plain-English status, contact history |
| System | Plain-English status of Thermowatt and the Tapo controller, settings links |
| Device Energy | Per-device energy and estimated tariff-valued costs for Tapo devices, daily and monthly tables, history (see [DEVICE_ENERGY.md](DEVICE_ENERGY.md)) |

Grey = off or inactive, blue = on or active. The colour of a control always follows the **observed** state;
a manual request, a queued request waiting for off-peak and an unknown status each have their own label
(`Fan: manual / automatic / off / status unknown`) and an unknown status is inert.

## Layout

Native sections views, no HACS, no theme changes. On a 4-column screen (1920 px) Home is
`[power flow | energy | hot water | weather]` over `[Main Bathroom | Ensuite | lights and doors (2 columns)]` and
fills about 57 % of the viewport. At 1366 px it needs a little scrolling (1.14x the viewport), at 1280 px about
1.4x, and on a phone it is a single readable column. Measured in a real frontend on every CI run (no overlap, no
horizontal overflow, readable text).

## Install / upgrade (nothing is overwritten, no integration is reset)

Existing configuration entries, entity IDs, learned baselines, towel schedules and saved options are untouched.

1. **Tapo Smart Controller v0.3.1** (from `MuntedDaze/tapo-smart-controller`): replace the whole
   `/config/custom_components/tapo_smart_controller/` directory, then **restart Home Assistant** (required).
   Saved options are kept; open the integration's *Configure* to see the new plain-English screens.
2. **Power-flow card:** replace `/config/www/thermowatt/thermowatt-power-flow-card.js` with
   `homeowner/www/thermowatt-power-flow-card.js`. To bypass the browser cache, edit the dashboard resource URL
   (Settings -> Dashboards -> ⋮ -> Resources) to `/local/thermowatt/thermowatt-power-flow-card.js?v=2`, then
   hard-refresh. No restart.
3. **Energy package:** replace `/config/packages/thermowatt_home_energy.yaml` with
   `homeowner/home_energy_package.yaml`. Run **Developer Tools -> YAML -> Check configuration**, then
   **Reload template entities**. The daily utility meters and the integration sensor are defined exactly as
   before, so **no restart is needed** and their accumulated data is kept (unique IDs are unchanged).
4. **Dashboard:** open `/home-control/` -> ⋮ -> Edit -> ⋮ -> **Raw configuration editor**, replace the content with
   `homeowner/home.yaml`, save. Only that dashboard changes.

Dependencies: Home Assistant 2024.8 or newer, Tapo Smart Controller 0.3.1. No HACS cards.

## Power-flow card

SEMS+-style three nodes: solar top, house bottom left, grid bottom right; green = solar supply and export,
orange = import, grey and stationary = inactive; chevron speed proportional to power (3 / kW seconds, 0.5-8 s);
label **Grid Import / Export / Idle / Unavailable**; kW to three decimals. Unavailable, unknown or stale
(> 15 min) readings show `--`, never zero. A line is drawn only when every measurement it needs is present and the
three readings agree (house = solar - export + import within a tolerance); otherwise it stays grey with a
"Readings not in sync" note. Units must be W or kW. Reduced-motion mode shows static arrows that still point in the
flow direction. Dependency-free SVG, redraws only when a value changes, theme-aware (light and dark).

## Energy: how the figures are obtained, and what was investigated

| Figure | Source and rule |
| --- | --- |
| Live solar / house / grid | measured GoodWe entities (W) -> kW |
| Solar today | the inverter's own daily generation |
| Grid import / export today (Home tiles) | Home Assistant **long-term statistics** (`statistic` card, change over the local day) on the verified lifetime counters: retroactive, available from day one, no new metering |
| Household today | energy balance **solar + import - export** from the inverter counters (a measured figure; battery-free only) |
| Solar used directly / self-consumption % | solar - export, and that divided by solar (>= 1 kWh generated) |
| Integrated household estimate | `sensor.home_consumption_estimate_today`: integration of sampled house power; **labelled an estimate** because outages leave gaps |

**Status sensor** `sensor.home_energy_status` (`ready`, `collecting_first_day`, `sources_unavailable`,
`inconsistent`, `battery_unconfirmed`) drives the dashboard. While it is not `ready` the Home screen shows
"Collecting daily data" (or the specific reason) instead of unavailable tiles; nothing is ever turned into zero.

Rules for `ready`: battery confirmed absent; solar, import and export counters are numeric kWh, non-negative and
reported within 30 min; the lifetime import/export counters are **not declared as a non-cumulative
`measurement`** (`total` and `total_increasing` are accepted, and a missing state class is accepted because
`utility_meter` does not need one; the inverter's daily generation counter is not required to have any particular
class); the daily meters have a valid first reading and their `last_reset` falls from **30 seconds before to 2
minutes after this local midnight** (a scheduled reset fires at 00:00:00), so a meter created at 00:09, one last
reset at 23:55 the day before, a missed midnight reset or a stale previous-day reset is rejected; and export does
not exceed generation (strict, no tolerance, never clamped). Midnight uses `now()` in local time, so Hobart's
daylight-saving changes (2 am) do not matter.

**What `ready` cannot prove:** Home Assistant cannot show whether an inverter counter was available through
midnight. If it was offline, the gap is added to the first reading after it returns, so that day can be
overstated. The status sensor's `limitation` attribute says so; check the morning figures after any outage.

Findings on the readings you reported:

* The two raw import/export utility meters showing `unknown` with `last_valid_state: None` immediately after
  installation is **expected Home Assistant behaviour, not a mapping error**: a utility meter takes its first
  reading from the next change of its source counter after start-up. The GoodWe lifetime counters only change in
  0.1 kWh steps, so import/export meters can wait minutes or (for export at night) hours. The package now reports
  this as `collecting_first_day`, and a wrong unit, missing `state_class` or stale counter as `sources_unavailable`.
  If a meter is still `unknown` hours after a counter has visibly changed, check Developer Tools -> States on the
  source counter for `unit_of_measurement: kWh` and `state_class: total_increasing`.
* Counter resets (a counter decreasing) are handled by the utility meter as a new cycle; restart persistence is
  provided by HA's own state restore for utility meters and the integration sensor.
* The historical long-term statistics are used directly on the Home screen. The daily meters are only needed for the
  derived figures, which Home Assistant cannot compute from statistics inside a template.
* I could not read your live entity registry from here; the unit/state-class checks above are therefore enforced
  by the package at run time rather than assumed.

## Limitations (need supervised testing on your system)

* The dashboard was rendered by a real Home Assistant frontend (Home Assistant 2026.11) with synthetic entities;
  it has not been viewed on your own instance.
* No physical device was operated; towel, fan and humidity behaviour is simulated or replayed.
* Home needs a little vertical scrolling below about 1400 px width; first-day energy figures appear after the first
  midnight following installation.
