# Unified Home dashboard

A separate, optional dashboard that combines solar/grid/house power flow, weather, hot water,
lights, doors and both bathrooms. It does **not** touch the existing Thermowatt or Tapo
dashboards: install it as a **new** dashboard, check it, and only then (if you want) retire the others.

Canonical source: `homeowner/home_mapping.yaml` (entity IDs) + `tools/build_home_dashboard.py`
(generator). Outputs are committed and checked in CI: `homeowner/home.yaml`,
`homeowner/home_no_custom_card.yaml`, `homeowner/home_energy_package.yaml`.
Regenerate: `python tools/build_home_dashboard.py`; verify: `--check`; list entities and
unresolved mappings: `--report`.

## Views

| View | Contents |
| --- | --- |
| Home | Power-flow diagram, today's energy, Rokeby weather, compact hot water + 12 h override toggle, dining/living room lights, garage and front-door status, Main Bathroom and Ensuite cards |
| Energy | Power flow, today's figures, retroactive long-term statistics, 24 h power history |
| Hot water | Status, hold/resume/override controls (each confirmed), tank history |
| Bathrooms | Both bathroom cards plus humidity/temperature history; link to the tuning options |
| Doors | Garage and front-door **monitoring only** |
| System | Tapo and Thermowatt health and settings links |

Grey = off or inactive, blue = on or active. Tapping a toggle never acts on a stale guess: the
colour shows the **confirmed** state, and starting heating (towel rail, 12 h override) asks first.

## What you must supply once (not guessed)

`python tools/build_home_dashboard.py --report` lists these. Open `homeowner/home_mapping.yaml`:

| Key | Why | Find it |
| --- | --- | --- |
| `weather.entity` | Rokeby TAS weather | Developer Tools -> States, filter `weather.` (Bureau of Meteorology or Met.no integration) |
| `lights.dining_room.entity`, `lights.living_room.entity` | the two light toggles | Developer Tools -> States, filter `light.` |
| `energy.battery_present` | shipped as `unknown`: "solar used directly" and self-consumption stay unavailable until you set `false` (no battery). `true` keeps them withheld (cannot be derived with a battery) | your inverter |

Until set, the card is replaced by a "mapping needed" note. After editing run the generator and
re-paste the YAML. All GoodWe entities in the file are marked `verified` (live registry, 12 Nov 2026).

## Install (nothing is overwritten, Home Assistant is not restarted)

1. **Custom card (recommended, no HACS):** copy `homeowner/www/thermowatt-power-flow-card.js` to
   `/config/www/thermowatt/`. In **Settings -> Dashboards -> ⋮ -> Resources -> Add resource** use URL
   `/local/thermowatt/thermowatt-power-flow-card.js`, type **JavaScript module**. Hard-refresh the browser.
   Without it, use `home_no_custom_card.yaml` (native tiles, no animation).
2. **New dashboard:** Settings -> Dashboards -> Add dashboard -> *New dashboard from scratch*, title
   **Home (new)**. Open it -> ⋮ -> Edit -> ⋮ -> **Raw configuration editor**. Paste the contents of
   `homeowner/home.yaml` (or the no-custom-card file) over the *empty* new dashboard and save.
3. **Optional energy package** (daily import/export/household/self-consumption figures): save
   `homeowner/home_energy_package.yaml` as `/config/packages/thermowatt_home_energy.yaml` (packages must
   already be enabled in `configuration.yaml`: `homeassistant: packages: !include_dir_named packages`), run
   **Developer Tools -> YAML -> Check configuration**, then reload or restart at a time you choose. Daily meters
   start counting when installed; the **statistics** cards on the Energy view are retroactive.
4. Existing integrations and entities are unchanged: do not reinstall or reset either integration. The
   dashboard needs **Tapo Smart Controller v0.3.0** (entity contract `homeowner/tapo_entity_contract.json`,
   copied from the Tapo repo `dashboards/home_entity_contract.json`).

Dependencies: Home Assistant 2024.8 or newer (sections view, tile `state_content`, `perform-action`).
HACS is **not** required. No third-party card is used.

## Power-flow card

SEMS+-style three nodes: solar top, house bottom left, grid bottom right. Green chevrons = solar supply
and grid export, orange = grid import, grey and stationary = inactive. Chevron speed is proportional to
power (3 / kW seconds, limited to 0.5-8 s). The grid label changes between **Grid Import**, **Grid Export**,
**Grid Idle** and **Grid Unavailable**; values are kW to three decimals. Unavailable, unknown or stale
(> 15 min) readings show `--`, never zero, and their lines stay grey. Simultaneous solar and import,
night-time consumption and zero flow are handled; a path is animated only when every measurement it needs is present and the three readings agree (house = solar - export + import within a tolerance), otherwise it stays grey with a "Readings not in sync" note; units must be W or kW; reduced-motion shows static arrows that still point in the flow direction (see `tests/js/power_flow_card.test.mjs`). It is a single
dependency-free file using SVG, redraws only when a value changes, honours `prefers-reduced-motion`, and
uses theme variables for light and dark.

## Energy calculations

| Figure | Source |
| --- | --- |
| Live solar / house / grid | measured GoodWe entities (W) -> kW |
| Today's solar | inverter's own daily generation |
| Grid import / export today | daily `utility_meter` on the lifetime counters, shown only once the meter covers a **full day** |
| Household today | integration of measured house power (`max_sub_interval`), full-day only |
| Solar used directly | solar today - export today; needs confirmed no battery, a full-day export meter, fresh sources and export <= generation (otherwise unavailable, never clamped) |
| Self-consumption % | the same conditions plus >= 1 kWh generated |

Daily meters start when the package is installed, so on the **first day** these figures are unavailable (the
Energy view shows the raw meters as "partial on the day installed"; its statistics cards are retroactive).
From the first midnight onward they are exact. A meter is trusted only if its `last_reset` is at or before
00:05 today; sources must have reported within 30 minutes (house power 15). EMHASS forecasts are never shown
as measurements, and an unavailable source gives `unavailable`, not a guessed zero.

## Limitations (need supervised testing)

* Rendering: the card was rendered in a real browser (desktop/phone widths, light/dark, reduced motion) and the full dashboard is rendered by a real Home Assistant frontend in CI (`.github/workflows/home-dashboard-frontend.yml`, synthetic states, service calls recorded not executed). It has not been viewed on YOUR Home Assistant.
* Weather, lights and battery presence are unmapped/unconfirmed until you fill the mapping file.
* No physical hardware testing has occurred; towel-rail and fan behaviour is simulated (Tapo v0.3.0).
* The package's daily meters start at installation.
