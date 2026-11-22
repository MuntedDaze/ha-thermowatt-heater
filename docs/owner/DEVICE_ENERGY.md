# Device Energy view

The seventh view of the unified Home dashboard. It reports the electricity used by the individual Tapo
devices that expose energy monitoring through Home Assistant: **today**, **month to date**, **previous completed
months**, a monthly comparison, per-device monthly history and the last seven days. It is separate from the
whole-house Energy view and **read-only**: it never sends a command and never polls a device.

## Where it lives and why

* **Thermowatt repo** (the dashboard repo): the card `<thermowatt-device-energy-card>` is inside
  `homeowner/www/thermowatt-power-flow-card.js` (one resource, no new file to register), configured by the
  generated `homeowner/home.yaml`.
* **Tapo Smart Controller is untouched.** Energy monitoring is independent of the control algorithms: if the card
  fails or the view is removed, the controller, the Home screen and every other view carry on.
* **No new entities, no new helpers, no package.** The accounting is Home Assistant's own **long-term statistics**
  (persistent, survives restarts, handles counter resets, keeps history indefinitely). Nothing is reset or
  recreated, so there is nothing to upgrade or migrate and no existing counter or statistic is touched.

## Layout

On a wide screen the view is three columns (summary and today | month to date and previous months | charts,
per-device history and the last seven days); on a phone it is one column. These are three instances of the same
card with a `part` option (`summary`, `daily`, `monthly`, `history`; default `all`), and they **share one
statistics load**, so the page makes the same number of queries as a single card would.

## Discovery (nothing hardcoded)

At run time the card reads Home Assistant's device and entity registries and finds every device of the configured
platforms (default `tplink` and `tapo`, i.e. the core TP-Link/Tapo integration and the common custom Tapo
integration) that has energy-monitoring sensors:

1. **One source per device**, so today / month / lifetime counters of the same device are never added together:
   the best cumulative counter (`device_class: energy`, state class `total` or `total_increasing`, unit kWh/Wh/MWh;
   the lifetime "total consumption" is preferred over "today" or "this month"), otherwise its measured **power**
   (`device_class: power`, W/kW), whose energy is then an **estimate** (mean power x time) and is marked *est.*
2. **Real names:** the device's name as you configured it in Home Assistant.
3. A Tapo device without any energy or power sensor (a bulb, for example) is **not shown as zero**: it is counted
   in "N without energy monitoring".
4. Hidden entities are ignored; a device appears once however many entities it has.

**Include / exclude.** In `homeowner/home_mapping.yaml` (`device_energy`): `exclude` (device names or entity IDs),
`include_only`, or `exclude_label` (any Home Assistant label ID). Regenerate and paste the dashboard again. **Adding a
device** needs nothing: new energy-capable Tapo devices appear automatically.

## Tariff and cost rules

* **Tariff windows are not duplicated:** they are read from `energy_monitoring/entity_map.yaml`, the same source as
  the Thermowatt energy package (Aurora Tariff 93: weekdays 07:00-10:00 and 16:00-21:00 on the **fixed AEST clock**
  all year; everything else off-peak).
* **Allocated when consumed:** every statistics bucket (5 minutes for the last ~10 days, 1 hour before that) is
  assigned to the tariff in force at the start of that bucket, not the current tariff. Windows are hour-aligned,
  so allocation is exact at these resolutions.
* **Rates in one place:** `device_energy.rates` in `homeowner/home_mapping.yaml` (currently off-peak **$0.1419** and
  peak **$0.1907** per kWh). The list is **append-only**: when prices change, add an entry with its `effective_from`
  date; earlier periods keep the rate that applied then, so history is never silently recalculated.
* **Estimated tariff-valued operating costs, not Aurora charges.** No daily supply charge, no solar feed-in credit,
  and no assumption that device energy came from the grid (there is no device-level solar attribution). Household
  grid spending remains separate on the Energy view.

## Day and month boundaries

Days and months roll over at **midnight Australia/Hobart** (daylight-saving aware: a 23-hour and a 25-hour day are
handled), independent of the browser's time zone. Completed months are never deleted: they are recomputed from
the persistent statistics, so history survives month and year rollovers. The active month is labelled, and when
monitoring began partway through a day or month the row shows *from 11 Nov* and the total says "partial".

## Accuracy limits (read this)

* Resolution is the statistics resolution (5 minutes recent, 1 hour older). A device that reports slowly, or a
  gap in reporting, is attributed to when Home Assistant recorded it; a missing bucket is **skipped, never zero**.
* Power-only devices are estimates (mean power over each bucket).
* Counter resets are handled by Home Assistant's statistics; a device that is unavailable simply has no data for
  that time.
* Existing history is reused: anything the recorder already holds is reported (the card fetches the last 6 months,
  `history_months`). Statistics begin when an entity first got a state class, so earlier periods show as partial.
* Costs use the rate schedule's dates; if your actual rates differed in the past, add dated entries.

## The one thing I could not check

I have no access to your Home Assistant registry, so the exact entities your Tapo devices expose are not verified.
The discovery rules above avoid assuming names, but if a device does not appear, or a wrong counter is picked, run
this once in **Developer Tools -> Template** and send me the output:

```
{% for integ in ['tplink', 'tapo'] %}{% for e in integration_entities(integ) if state_attr(e, 'device_class') in ['energy', 'power'] %}
{{ integ }} | {{ device_attr(device_id(e), 'name_by_user') or device_attr(device_id(e), 'name') }} | {{ e }} | {{ state_attr(e, 'device_class') }} | {{ state_attr(e, 'state_class') }} | {{ state_attr(e, 'unit_of_measurement') }}
{% endfor %}{% endfor %}
```

## Install

Nothing extra: the Device Energy view is part of `homeowner/home.yaml`, and its card is in the existing
`/config/www/thermowatt/thermowatt-power-flow-card.js` (replace the file; hard-refresh). No package, no restart.
