# Energy monitoring and dashboard

A Home Assistant package and dashboard for solar, grid, tariff cost, hot water, appliances and monitoring health. It complements the Thermann Controller and is independent of it.

**Read-only.** It creates sensors and four tariff-rate helpers. It calls no service, publishes nothing to MQTT, never writes to the heater and has no buttons. Nothing in this folder is installed automatically: every step below is done by the owner.

## Files

| File | Purpose |
| --- | --- |
| `entity_map.yaml` | The only file you edit: which entity is which. |
| `build.py` | Regenerates `generated/` from the map. `--check` fails if it is out of date. |
| `generated/packages/thermann_energy.yaml` | The package to copy into Home Assistant. |
| `generated/dashboards/energy.yaml` | The dashboard (seven views, built-in cards only). |
| `report.py` | Day/week/month/year tables from Home Assistant's own statistics. |
| `calc.py` | The reference arithmetic the templates are tested against. |
| `ENTITY_CONTRACT.md` | What this package provides to, and needs from, the controller. |
| `PROGRESS.md` | Checkpoint: what is done and what is next. |

## What it shows

| Dashboard view | Contents |
| --- | --- |
| Overview | Live solar, house, grid import/export, solar used at home, untracked load, tariff period and price; today's totals, self-consumption, self-sufficiency and net cost; hot-water summary; monitoring health. |
| Hot water | Mode, target, tank reading, plan and decision reason, cloud polling and request counts. With a CT: element watts, kWh, runtime, cycles, grid/solar split, imported cost, solar opportunity cost and the last heating cycle. |
| Costs | Rates, peak and off-peak import, import cost, feed-in earned, import avoided by solar and net cost, for today, week, month and year. |
| Appliances | Every circuit and smart plug, live and per day/month, plus *Other / untracked*. |
| History | Daily, weekly, monthly and multi-year totals; solar forecast against actual. |
| Energy | Home Assistant's own Energy cards. |
| Health | Missing, unavailable and stale sources; rates set; untracked residual; what is still unmapped. |

## Install

1. **Map your entities.** Edit `entity_map.yaml`, then regenerate:
   ```bash
   python energy_monitoring/build.py
   ```
   Entries marked `[unverified]` follow the documented naming pattern; confirm them in *Settings → Devices & services → Entities*. A wrong or missing entity is not fatal: it shows on the Health view.
2. **Copy the package** `generated/packages/thermann_energy.yaml` to `/config/packages/`. If `configuration.yaml` has no packages line yet, add:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
3. **Check and restart.** *Developer tools → YAML → Check configuration*, then restart Home Assistant.
4. **Set the four rates** in *Settings → Devices & services → Helpers* (or on the Costs view): `EM peak import rate`, `EM off-peak import rate`, `EM feed-in rate`, `EM daily supply charge`. Take them from your Aurora bill, including GST. Until the three per-kWh rates are above zero, costs are not counted and Health reads *degraded*.
5. **Configure the Energy dashboard** (*Settings → Dashboards → Energy*):
   - Grid consumption: your import meter, *Use an entity with current price* → `sensor.em_import_price`.
   - Return to grid: your export meter, price entity → `sensor.em_feed_in_price`.
   - Solar production: your solar energy sensor.
   - Individual devices: each circuit energy sensor, each smart-plug energy sensor and `sensor.em_untracked_energy`. For a plug behind a CT, set the CT circuit as its *upstream device* so it is not counted twice.
6. **Add the dashboard.** *Settings → Dashboards → Add dashboard → New dashboard from scratch*, open it, *Edit → ⋮ → Raw configuration editor*, and paste `generated/dashboards/energy.yaml`.

### Adding the Shelly (or any other CT meter) later

1. In `entity_map.yaml`, set `power` for each circuit you clamped to the meter's power entity in watts. Set `energy` if the meter has a kWh total; leave it blank otherwise and the package integrates the power.
2. For any smart plug wired downstream of a clamped circuit, set its `circuit` to that circuit's key.
3. Regenerate, copy both files again, restart.

Nothing depends on the Shelly model. The package wraps each circuit in its own `sensor.em_<key>_power` and `sensor.em_<key>_energy`, so replacing the meter later keeps the history. A reversed clamp still reads as consumption.

## Verification checks

Do these once after installing, and again after adding a meter.

| # | Check | Expected |
| --- | --- | --- |
| V1 | Health view | *ok*, nothing missing or stale. |
| V2 | Turn a known load on while the sun is down | `Grid import` rises, `Grid export` stays 0. If reversed, flip `grid.export_positive`. |
| V3 | `sensor.em_tariff_period` at 07:00 and 10:00 AEST on a weekday (08:00 and 11:00 Hobart time during daylight saving) | Changes to *peak*, then *off_peak*. Health attribute `tariff_matches_controller` is true. |
| V4 | Next morning | `EM grid import daily` reset at midnight; `EM solar daily` did not go backwards or double. |
| V5 | After one full day | Costs view import cost ≈ peak kWh × peak rate + off-peak kWh × off-peak rate. |
| V6 | After one full day | `EM house energy today` (meter balance) and the *House used* statistic (integrated power) agree within a few percent. |
| V7 | Health view, untracked residual | Not persistently negative. |
| V8 | With the hot-water CT: let the heater run | `Element drawing power` turns on within 30 s of ~3 kW; after it stops, *Last heating cycle* shows duration, kWh and the grid/solar split. |
| V9 | Heater running in full sun with export still positive | `From solar now` ≈ element power, `From grid now` ≈ 0. |
| V10 | Compare a month with the Aurora bill | Peak and off-peak kWh within about 2 %. |

## How the numbers are made

- **Grid import/export power:** the signed meter power, split by `grid.export_positive`.
- **Solar used at home:** solar − export, never below zero.
- **Tariff period:** Aurora Tariff 93 runs on fixed AEST all year, so with `clock: standard` the period is taken from UTC+10 and does not move with daylight saving. Public holidays are treated as ordinary weekdays, as the controller does.
- **Cost and earnings:** each step of the import or export meter is multiplied by the price in force when it arrives and added to a running total. A later rate change does not re-price earlier energy. Energy that arrives while a rate is unset is counted in the sensor's `unpriced_kwh` attribute instead of being costed at zero silently.
- **Hot water, grid versus solar:** the heater is the load you can move, so it is charged with the import it causes: grid = min(element power, grid import); the rest is solar.
- **Imported cost versus solar opportunity cost:** *imported cost* is grid energy × import price and is on your bill. *Solar opportunity cost* is solar energy × feed-in rate: income you gave up by not exporting. They are separate sensors and are never added together.
- **Other / untracked:** house power − (every mapped CT circuit + every smart plug that is not behind a mapped CT). A plug behind a CT is left out of the sum, so no load is counted twice.
- **Day, week, month and year:** read from Home Assistant's long-term statistics of the cumulative sensors. Days follow Home Assistant's local calendar, so the 23- and 25-hour daylight-saving days are each one day.

## Limits to know about

- **No backfill.** Cost, peak/off-peak and solar/grid totals start at zero on the day of installation. Solar, import, export and smart-plug history that Home Assistant already has is used as is.
- **Sensors report at different moments.** GoodWe updates every few tens of seconds, plugs less often. Live *untracked* and the hot-water split can be briefly off around a switch; the energy totals average this out.
- **Integrated energy.** Where a meter has no kWh total, energy is the integral of power (left Riemann sum, capped at 5-minute steps). It is slightly less exact than a metered total.
- **Unavailable sources.** An unavailable reading makes the dependent sensor unavailable, not zero. A smart plug that is offline contributes nothing to the tracked sum, so its load appears as untracked until it returns; Health lists it.
- **Inverter asleep at night.** If the solar entity goes unavailable overnight, set `solar.zero_when_unavailable: true`.
- **Heating cycles.** Start and end are debounced by 30 s and 60 s. The tank reading comes from the cloud and can be one poll interval old at each end; the age is recorded with it. Each cycle is one state of `sensor.em_hot_water_last_cycle`, kept for the Recorder's retention period (10 days by default).
- **Until a CT is installed** there is no measured element power. The Hot water view shows the controller's information and a note; it does not estimate watts.

## Reports

```bash
python energy_monitoring/report.py --request
```

prints a `recorder.get_statistics` action. Paste it into *Developer tools → Actions*, set the dates, run it and save the response as a file. Then:

```bash
python energy_monitoring/report.py response.yaml --period month
```

prints a Markdown table by day, week, month or year. The script reads the saved file only; it never connects to Home Assistant.

## Tests

```bash
python -m pytest tests/test_energy_monitoring_build.py tests/test_energy_monitoring_templates.py
```

The tests render the generated templates offline and compare them with `calc.py`; check that every entity the dashboard uses exists; and check that neither file contains a service call, a control or a heater entity. CI also runs Home Assistant's `check_config` on the package inside the official image with networking disabled (`.github/workflows/energy-monitoring.yml`). The dashboard has not been loaded in a real Home Assistant frontend.
