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

On a wide screen the view is three columns (summary and whole-house balance | today, month to date and
previous months | charts, per-device history and the last seven days); on a phone it is one column. These are three
instances of the same card with a `part` option (`summary`, `balance`, `daily`, `monthly`, `history`; default
`all`), and they **share one statistics load**, so the page makes the same number of queries as a single card would.

## Discovery (nothing hardcoded)

At run time the card reads Home Assistant's device and entity registries and finds every device of the configured
platforms (default `tplink` and `tapo`, i.e. the core TP-Link/Tapo integration and the common custom Tapo
integration) that has energy-monitoring sensors:

1. **One source per device**, so today / month / lifetime counters of the same device are never added together:
   the best cumulative counter (`device_class: energy`, state class `total` or `total_increasing`, unit kWh/Wh/MWh;
   a lifetime "total consumption" is preferred, then the monthly, then the daily counter), otherwise its measured **power**
   (`device_class: power`, W/kW), whose energy is then an **estimate** (mean power x time) and is marked *est.*
2. **Real names:** the device's name as you configured it in Home Assistant.
3. A Tapo device without any energy or power sensor (a bulb, for example) is **not shown as zero**: it is counted
   in "N without energy monitoring".
4. Hidden entities are ignored; a device appears once however many entities it has.

**Include / exclude.** In `homeowner/home_mapping.yaml` (`device_energy`): `exclude` (device names or entity IDs),
`include_only`, or `exclude_label` (any Home Assistant label ID). Regenerate and paste the dashboard again. **Adding a
device** needs nothing: new energy-capable Tapo devices appear automatically.

## Whole-house energy balance

A compact section (a Sankey-style diagram, a Today / month toggle and a table of ten figures) that relates the
inverter's measurements to the individually monitored devices. It is **energy only**: device costs elsewhere in
this view are tariff-valued estimates, not grid spending, and **no solar is attributed to individual devices**.

| Figure | Definition (confirmed battery-free installation) |
| --- | --- |
| Solar generation, Grid import, Grid export | long-term statistics of the verified GoodWe counters in `homeowner/home_mapping.yaml` (`energy.solar_today_energy`, `grid_import_total`, `grid_export_total`) |
| Solar used directly | generation − export |
| Household consumption | generation + import − export |
| Monitored devices | sum of the Tapo devices' statistics (one source per device) |
| Unmeasured consumption | household − monitored |
| Solar self-consumption | solar used ÷ generation (shown from 1 kWh generated) |
| Solar independence | solar used ÷ household (shown from 0.5 kWh consumed) |
| Monitored share | monitored ÷ household |

* **Nothing new is measured or polled.** The balance reuses Home Assistant's recorder statistics for the existing
  counters and the devices; there is no new meter, helper, package or background service. Daily-counter resets
  (the inverter's daily generation counter, the Tapo daily and monthly counters) are handled by the statistics
  themselves: each reset starts a new cycle, so the `change` over any period is the energy used.
* **Same period for every figure.** All sources are summed over the same **complete hours** (to the last whole hour;
  the running hour is excluded so reporting latency cannot distort the comparison), from local midnight (Today)
  or the first of the month (Month, midnight Australia/Hobart, DST aware). Today shows "collecting" until the first
  complete hour.
* **Invalid results are withheld with the reason, never clamped.** Missing or incomplete statistics for any
  inverter source, a source without long-term statistics, or export above generation by more than the counters'
  resolution (3 × 0.1 kWh) withhold the whole balance. Within that resolution the result is rounded and a note says
  so. If monitored devices exceed household consumption by more than measurement error (the larger of 0.3 kWh
  and 5 %), only the unmeasured figure and monitored share are withheld, with an explanation (check for a device
  measured upstream of another, or a wrong source).
* **Incomplete is not unmeasured.** If a device has missing, late-starting or no statistics, monitored energy is
  shown as a lower bound (**≥**) and unmeasured consumption as an upper bound (**≤**), with a warning; it is never
  presented as confirmed. Energy estimated from power (**≈**) is flagged too.
* **Latency.** The newest hour is only used once Home Assistant has had ten minutes to compile its hourly row, so
  the balance may stop up to an hour and ten minutes behind the clock (the note says "to 6:00 pm"). Statistics are
  attributed to when Home Assistant recorded a reading, so a device that reports a minute late shifts at most that
  minute of its energy into the next hour; this can bias an hour's unmeasured figure slightly, and monthly totals
  not at all. Monitored devices in the balance therefore use complete hours only and can be slightly below the
  Today and month tables, which include the hour in progress.
* **Devices that cannot be used.** A monitored device whose statistics unit is not recognised (or that has no
  statistics) is counted as incomplete, so unmeasured consumption becomes an upper bound. A device with no energy
  or power sensor at all (a bulb) is genuinely unmeasured: its consumption is part of the unmeasured figure.
* **Solar counter.** Generation uses the inverter's daily generation counter through long-term statistics, which
  treat each reset as a new cycle. A glitch in that counter (a dip that is not a reset) would be counted as one;
  this has not been observed on the live entity and cannot be detected from statistics alone. Only mappings
  marked `verified` or `owner-confirmed` are used.
* **Battery.** The formulas only hold without a battery. The dashboard passes `battery_present` from the mapping
  (`false` for this installation); anything else withholds the balance.

## Tapo sources: daily and monthly counters

The 12 live devices (Dishwasher, Fridge, Washing Machine, JRIG, Server, Dryer, Network Cupboard, Main Towel Rail,
Main Fan, Garage, Ensuite Towel Rail, Ensuite Fan) each expose `sensor.<device>_current_consumption` (W),
`sensor.<device>_today_s_consumption` and `sensor.<device>_this_month_s_consumption` (kWh, `total_increasing`) and
**no lifetime counter**. Source selection is explicit: a lifetime counter if one exists, otherwise the **monthly**
counter (the fewest resets), otherwise the daily one, otherwise power (an estimate); a "yesterday", weekly or yearly counter is
never a source. A counter's kind is read from its translation key or the last words of its entity ID, never from the
device's name. Exactly one counter per device is used, so the daily and monthly counters are **never added together**.

**Cross-check.** The other counter is kept only as a check: the statistics-derived energy for today is compared with
the device's own daily counter, and for the month with its monthly counter. A row that differs by more than rounding,
5 %, or about a quarter of an hour at the device's present power is marked **≠ device counter**, and the balance
section shows both totals. (A device whose own day does not start at Hobart midnight will show a difference.)

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

## Source selection limits

Nested devices (a Tapo plug measuring a circuit that also contains another monitored plug) cannot be detected, so
their energy would be counted twice in "monitored"; the balance then reports the inconsistency only when monitored
exceeds household consumption. Exclude the outer device in `device_energy.exclude` if that is the case.

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
