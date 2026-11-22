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
  date; earlier periods keep the rate that applied then, so history is never silently recalculated. Every entry
  is validated (finite, non-negative prices; a real `YYYY-MM-DD` date; no duplicate dates), by the generator and again by
  the card.
* **Assumed historical rates:** only the *current* prices are confirmed, not the date they started, so the owner
  entry has `effective_from: null`. Costs for any period before a dated entry (here: all of them) are valued at the
  earliest listed price and marked **≈** with an explanatory note; they are **not verified historical costs**. kWh
  are never affected. If no rate is configured the card shows kWh and withholds cost (never $0). Once the start date
  of the current prices is known, put it in the entry: periods from that date become verified.
* **Estimated tariff-valued operating costs, not Aurora charges.** No daily supply charge, no solar feed-in credit,
  and no assumption that device energy came from the grid (there is no device-level solar attribution). Household
  grid spending remains separate on the Energy view.

## Statistics, units and completeness

* **Hourly for history, 5-minute only for the last hours.** Hourly long-term statistics cover the whole period (they
  are kept indefinitely). 5-minute statistics are used only for the last three hours, and only for an hour that has
  no hourly row yet, so no hour is counted twice and no retained history is skipped, whatever your recorder's
  short-term retention is. Day and month boundaries are whole hours, so allocation to the tariff is exact.
* **Units come from the statistics metadata** (`recorder/get_statistics_metadata`), not from the live sensor: Wh,
  kWh and MWh energy and W, kW and MW power are normalised to kWh. A source whose statistics unit is not recognised
  (or that lacks a sum or mean) is **not shown or guessed**; the summary says how many were left out.
* **Coverage is explicit.** For each row the card checks every *completed* hour of the period (the running hour is
  never expected). A recorded **zero** shows `0.000 kWh`; a device with no statistics shows "no statistics (not
  zero)" and is excluded from the total (which then says "N without data"); **`from <time>`** means statistics begin
  after the period starts; **`N h missing`** means hours inside the period have no statistics (a gap); and a
  total with any of these is marked **incomplete** (previous months: **partial**). Periods are bounded by their
  real calendar day or month.
* **Staleness:** the summary shows when the statistics were loaded. If a refresh fails, the last good figures stay on
  screen with "Latest refresh failed ... showing statistics last loaded at HH:MM"; after three refresh intervals
  without a refresh a "may be out of date" note appears. Failed loads are retried at most once a minute.

## Previous months are reconstructed, not archived

There is no ledger and no background job. Completed months are **recomputed on every load** from long-term
statistics for the devices and energy sources discovered **today**. So a device removed or disabled since, or a
device whose chosen source changed, drops out of (or changes) earlier months; the card says so under the table. If
you need frozen monthly totals, export them (for example Home Assistant's Energy dashboard statistics export, or a
copy of the table each month); that is intentionally not built here.

## Day and month boundaries

Days and months roll over at **midnight Australia/Hobart** (daylight-saving aware: a 23-hour and a 25-hour day are
handled), independent of the browser's time zone. The card deletes nothing, so history survives month and year
rollovers (subject to the reconstruction note above). The active month is labelled. This assumes a zone whose
midnight falls on a whole hour (Hobart does).

## Accuracy limits (read this)

* Resolution is one hour (5 minutes for the last few hours). A device that reports slowly, or a gap in
  reporting, is attributed to when Home Assistant recorded it; a missing hour is **skipped and flagged, never zero**.
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
