# Thermowatt owner handbook

[Start page](../../README.md) · [Upgrade](OWNER_UPGRADE.md) · [Every setting](SETTINGS.md) ·
[Dashboard/report](INTERFACE.md) · [Evidence](EVIDENCE.md) · [Local telemetry](LOCAL_TELEMETRY.md)

## Contents

- [Daily operation](#daily-operation)
- [Temperatures](#temperatures)
- [Solar and weekends](#solar-and-weekends)
- [Electricity and clocks](#electricity-and-clocks)
- [Cloud checks and learning](#cloud-checks-and-learning)
- [Worked examples](#worked-examples)
- [Troubleshooting](#troubleshooting)
- [Capability table](#capability-table)

## Daily operation

Home Assistant is the home computer joining readings, settings and controls.
The bridge App is the single connection to Thermann's cloud. MQTT/Mosquitto
carries local messages between the bridge and controller. The controller chooses
permitted heating; the native heater thermostat controls the actual element.
Neither dashboard authorises commands. Basic tariff control needs no solar,
forecast or dedicated circuit meter. One heater/controller and one bridge per
account are supported; other appliances need compatibility checks.

The Home view separates reported mode from requested plan. Pending is not
confirmation. Hold gives owner control priority. Resume re-inspects before
policy can act. An official-app change creates an owner hold when observed.
A change reversed entirely between reads can be missed. Use Hold for deliberate
intervention. Automatic OFF stops new routine commands, not an already-sent
command or the physical electricity supply.

**12hr Override62°C** requests Manual62 for12 hours, including peak, unless
cancelled. Expiry/cancellation reassesses the permitted policy. An already-active
legacy70 override keeps its target and expiry; a new press selects62. Unresolved
commands are reconciled, not replaced or replayed. Holiday dates use the household
zone; departure parks OFF and return reassesses. Owner holds and faults retain
their precedence. Existing entity IDs remain unchanged.

## Temperatures

The owner's agreed roles remain Manual45 overnight/weekend baseline, Manual62
normal weekday storage, optional economical Manual70 and configured peak OFF.
Supported role selections remain configurable; unrestricted setpoints are not
accepted. The owner chose this strategy after discussing it with a plumber.
It is not a universal storage recommendation or independently established compliance.

The [manufacturer guide, printed pages9–10 and17](https://www.thermann.com.au/thermann-cms/files/Thermann-Smart_Electric-Owners_Guide.pdf)
describes bottom-probe stratification, reheating at least8°C below target,
antibacterial behaviour and frost protection. App OFF leaves power connected
and does not suppress all native cycles. Consult the guide for your model/firmware.

One bottom probe does not describe all stored hot water or prove hygiene safety.
Hotter water may remain above cold incoming water after a shower. Occasional
62/70 operation does not independently establish microbiological compliance.
Follow appliance instructions, local requirements and professional advice.
This release adds no new temperature restriction or hygiene gate.

Near63°C, selecting70 may cause no useful heating because of native hysteresis;
Thermowatt can reject that pointless boost. At48°C with qualified surplus it may
select70 directly instead of45→62→70. Higher targets are not selected merely
because they exist. A missed62 target is not treated as an emergency.

Before either configured peak, a genuinely fresh bottom reading below the chosen
warning level (default35°C) can generate a low-water notice. Default observation
lead is30 minutes. Stale/unavailable means unverified, not measured cold. An alert
does not create peak permission. Old45-by06:00/42-by07:00 production warnings are
retired; saved legacy settings remain for rollback.

## Solar and weekends

Required weekday heating can use forecasts and raw signed export to choose
economical off-peak windows without a CT. Nominal tank/element ratings estimate
duration, never physical element ON/OFF or guaranteed ready-water quantity.
EMHASS remains optional. Its PV and house-load generation times/coverage are
checked independently. Missing or near-zero load uses a conservative household
floor rather than pretending all forecast PV is spare; no second forecasting
engine or double-counted appliance load is introduced.

On weekends (0.17.0), baseline 45 continues until the first fresh measured PV
report of at least 500 W (editable). There is no qualification delay and no
09:00 restriction. The window then stays latched until 18:00 household time:
passing clouds or a later fall below 500 W do not end it. Inside the window,
62 normal storage is planned with the EMHASS PV and household-load forecast to
be ready by the storage-ready time (16:00, with the 30-minute completion
margin); off-peak grid assistance is deliberately allowed. With no usable
forecast it starts at once. If PV never opens the window, it opens at the
latest start that still meets the deadline (15:30 for an already-warm tank,
where 62 only lets the thermostat reheat an afternoon draw). At 18:00 the thermostat target
returns to 45; that does not cool water already stored. The latch survives a
restart for that day; configured peak restrictions still take precedence. See
[the weekend strategy](../weekend/WEEKEND_STRATEGY.md).

Optional70 has separate stronger checks: enabled boost, useful heat, economic
benefit, measured surplus, available budgets and no unresolved protective exit.
It supports either a commissioned dedicated heater circuit meter (CT) or the
separately configured experimental CT-free GoodWe grid-meter setup. Turning
**Enable optional solar boost** on alone does not start boosting: automatic control
and all measurement, solar surplus, cost, peak-policy and safety requirements
must also be satisfied.
The3kW example needs3.3kW surplus for10 continuous minutes to start. Forecasts
or inferred watts cannot replace actual evidence. After startup it does **not**
require3.3kW remaining export. A dedicated CT may credit genuine measured heater
power only where allowed; the CT-free path never credits nominal element watts.

Without a CT, open **Configure → Solar & Meters → Set up experimental CT-free
solar**. Map genuine signed grid, inverter AC and house readings first. Verify
direction with a known load. The supported form checks fresh post-startup W/kW
evidence and site balance, records compatible permission and asks for explicit
experimental risk acceptance. It sends no command, enables no automation and
certifies no CT test. Source/unit/sign or heater-rating changes invalidate its
record. A failed commissioned circuit meter cannot silently downgrade.

| Independent choices | Result |
|---|---|
| Never peak; boost enabled | Qualified optional boost outside peak only |
| Never peak; boost disabled | Normal storage, no optional higher solar target |
| Allow peak solar; boost enabled | Qualified measured/economical peak solar permitted, with short-import exposure |

During authorised peak solar, over200W whole-house import for10 continuous
minutes withdraws permission. An acceptable sample resets the timer; required
grid evidence missing/stale withdraws immediately. Brief kettles/clouds need not
toggle the heater. The durable protective OFF requirement survives pending START,
faults, restart and sunshine returning until legitimately resolved. No uncertain
POST is blindly repeated. Cloud failure/backoff can prolong import.

After a solar-withdrawal OFF is **confirmed**, optional restart waits the configured
cooldown (default10 minutes) and renewed qualification; they can overlap. Ordinary
15-minute command spacing remains a separate minimum, so effective restart may
be later. A refused/pending OFF does not start the confirmed cooldown. Existing
protective OFF exceptions remain.

**Cloud OFF is software, not electrical isolation or proof of zero consumption.**
Native protective cycles, manual intervention and outages remain possible.
CT-free operation never claims physical element verification.

## Electricity and clocks

Enter **retail usage prices** in cents/kWh:17.02 means$0.1702/kWh. A3kW element
running for one hour uses about3kWh. Daily supply charges do not select windows.
Feed-in compensation is the export payment forgone by using solar at home.
Network charges are not automatically the retailer's prices on your bill.

Flat plans have no inherent peak. One tariff engine supports multiple daily
off-peak/shoulder/peak windows, weekdays/weekends, months and rate overrides.
The guided editor checks coverage, overlaps and seasonal gaps. An unconditional
zero-price retail period can be a zero-rate window; conditional credits/caps are
not inferred. Raw JSON remains an expert alternative for the same model.

Choose an IANA household zone (normally HA's configured zone), separately from
the tariff clock. Local follows daylight saving; fixed standard does not.
Jacob's Aurora example uses fixed AEST:07:00 tariff time is08:00 on a Hobart
summer wall clock. Verify the actual retail contract; Tasmania/Aurora is not a
universal default. [Every field and its units](SETTINGS.md) is indexed.

## Cloud checks and learning

Keep existing choices until deliberately changed. Select the same new mode in
the bridge App Configuration and controller **Advanced/System → Cloud checks
and data age**. There is still one scheduler and HTTP client, owned by the bridge.

| Mode | Healthy quiet interval / trade-off |
|---|---|
| Keep existing | Preserves earlier flags, qualification and numeric interval |
| Smart — Recommended | Up to8h overnight/90min daytime; useful decisions shorten the interval |
| Fixed30 — Compatibility |30-minute background checks, plus command checks/confirmation |
| Experimental minimum | Up to12h overnight/3h quiet daytime; greater outside-app detection delay |

Quiet intervals need confirmed steady baseline/OFF and safe local context, not
merely the previous command. The existing180-second controller lease expires
to fixed30 if HA stops. Restart inspects; stale temperatures never become fresh.
Prepeak observation and actual OFF are separate useful events. Every command's
exact-prior check and confirmation remain. Local readings do not each cause HTTP.
Outages can extend all healthy detection bounds. A short app change between
reads may be missed; use Hold for immediate, intentional owner intervention.

Smart ordinary status GETs reuse sessions with the existing bounded401 refresh/
retry; command preparation, POST and confirmation retain earlier proactive
authentication safeguards. No vendor token lifetime is assumed. Short sessions
can add401 traffic. A refused refresh locks safely; repeatedly restarting or
deleting private tokens/guard state is not an optimisation.

Learning uses clean dedicated-meter cycles only. Interruption, draw, changed
targets, gaps or sensor remapping reject/reset evidence. CT-free predictions stay
nominal. Learned planning retains its separate default-off gate and hardware
qualification; upgrade never turns it on. Thermal-state displays are estimates,
not whole-tank observations. [Reproducible comparisons and limits](EVIDENCE.md).

## Worked examples

- Quiet night: Manual45 is confirmed. The native thermostat maintains it;
  Smart arranges a later useful check. App changes can remain unseen for hours.
- Cloudy weekday, no CT: conservative estimates choose required62 in a permitted
  cheap window. Peak OFF still applies if the target was missed; no unsafe catch-up.
- Sunny weekend: the first fresh 500 W PV report opens the window; 62 is
  scheduled for the cheapest time before 16:00 and stronger measured surplus
  may justify 70. A passing cloud does not end the window; 18:00 returns 45.
- Peak kettle:400W import for3 minutes then export resets withdrawal. Continuous
  import for10 minutes requests OFF. Meter loss withdraws immediately, but cloud
  failure can leave restoration/OFF unconfirmed.
- App change: owner control is protected when observed, not instantly discovered.
  The fresh exact-prior check prevents overwriting a different current prior.

## Troubleshooting

| Symptom | Useful action |
|---|---|
| No heating | Check Automatic, Hold/Holiday, cloud state, observation age and blocking reason. Do not tick qualifications to hide a warning |
| Authentication locked | Preserve state/generation; inspect official app and the bridge's safe error category. Follow deliberate operator recovery, not repeated login/restart |
| Pending/uncertain command | Inspect official app and fresh status; never blind retry. Acknowledge only after checking; protective OFF debt may remain |
| Parked OFF after peak | Dedicated30-minute warning means permitted heating remains unconfirmed. Choose the intended state in the official app if available; no automatic recovery promise during outage |
| CT-free boost unavailable | Check genuine signed grid, usable AC/house, units, freshness, setup record, boost and chosen peak policy |
| Former CT missing | Keep fault/degraded control; inspect actual meter. Missing is not measured0W |
| Steady0W expires | Meter must actually republish; `last_reported` must advance. Fix reporting or leave physical authority unavailable; do not manufacture fresh template timestamps |
| No70 near62 | Hysteresis/useful heat and economic/window checks intentionally reject pointless switching |
| Forecast tiny load | Verify original EMHASS generation/series. Conservative floor prevents imaginary surplus |
| Polling choice not applied | Match both choices; inspect accepted plan/lease. Unsupported/mismatched choices fall back conservatively |
| Frequent activity | Heartbeat now publishes at15-minute cadence or supervision changes. Internal checks stay fast; exact last completion is in diagnostics. Keep watchdogs |
| Technical code unclear | Read the focused Home plan and copy the diagnostic report; raw codes remain for compatible automations |

**Configure → Copy diagnostic report** opens a native multiline field. Select all
and copy; reopen for a fresh snapshot. Integration menu → Download diagnostics
provides JSON. Reports omit secrets and unnecessary identifiers. Review HA's
wrapper metadata before sharing. Never paste private state files or raw HTTP bodies.
The bounded200-event history records timestamped significant changes; very recent
events can be lost before its delayed diagnostic save. Critical command persistence
remains separate. A diagnostic-save fault cannot authorise or interrupt commands.

## Capability table

| Feature | Status / limit |
|---|---|
| Four-state/owner/fault/exact-prior/confirmation | Existing operational guarded path; offline tests are not physical commissioning |
| Required heating without CT/solar/EMHASS | Supported operational configuration |
| Weekend measured-PV comfort | New policy, deliberate off-peak grid assistance; owner validation after installation |
| CT-free optional peak solar | Explicit experimental mode; grid authority and short-import/unconfirmed-OFF exposure |
| CT-measured solar | Real circuit commissioning required; no electrical-isolation claim |
| Smart/Minimum | Explicit choices; bounded healthy owner-detection delay and fixed fallback |
| Learning display / learned control | Diagnostic evidence / separate default-off qualified authority |
| Thermal state and exposure | Inferred/nominal diagnostics, not metered energy or hygiene proof |
| Flat/TOU/shoulder/seasonal/midday windows | One supported model; owner verifies actual contract |
| Block/tier/demand/controlled-load/dynamic feed-in | Future extension requiring history/metering/eligibility; not accurate billing now |
| Arbitrary setpoints or local commands | Unsupported; guarded45/62/70 roles only |
| Local read-only temperature | No supported interface established; [feasibility](LOCAL_TELEMETRY.md) |
| Public distribution and live deployment | Deferred / not performed by development |
