# Thermann Shadow Planner 0.2.0 — Phase 2A owner-review candidate

This continues draft PR #9 and the existing planner; it is not a bridge rewrite.
Thermowatt stays **v1.3.8**, with its files, credentials, tokens, lockouts, options,
MQTT identities and disabled command/on-demand settings unchanged. Do not merge
or deploy this candidate automatically.

## Boundaries and configuration

Only existing Home Assistant states are read. A fixed **one-minute local timer**
samples the meter and updates recommendations. There are no network clients,
MQTT writes, heater services, authentication changes or cloud-refresh triggers.
No option enables control. EMHASS is not required. Existing bridge polling stays
30 minutes with a minimum 60-minute ordinary-error cooldown.

Entity selectors keep the owner's GoodWe/HK1000 and Thermann IDs. The reported
bottom temperature is used directly. The owner accepts its stratification limits;
there is no virtual reserve/stratification model or additional hardware requirement.
PV and house power are displayed, but only measured net grid power drives solar
opportunities. W/kW are checked and explicitly normalised. Raw signed grid power
is displayed unchanged in sign. The owner's load-tested convention remains
**positive = export**, negative = import; it is editable, never auto-inverted.

Fresh setups use owner-confirmed meter/tariff flags. Existing saved overrides,
including earlier false flags, prices, mappings and units, are preserved. A saved
0.1.0 placeholder tariff must be reviewed deliberately in Configure; it is not
silently replaced or treated as a newly confirmed contract.

## Confirmed owner tariff defaults

| Item | Default |
| --- | --- |
| Peak import | AUD 0.361878/kWh |
| Off-peak import | AUD 0.170200/kWh |
| Export compensation | AUD 0.092760/kWh |
| Weekday peaks | 07:00–10:00 and 16:00–21:00 **fixed AEST, UTC+10** |
| Weekends | Off-peak all day |

In Hobart daylight-saving time those peaks display at 08–11 and 17–22. During
standard time they display at 07–10 and 16–21. Do not manually shift the tariff
JSON for DST. All rates and complete weekly periods remain editable. Days are
Monday=0 through Sunday=6. Start is inclusive, end exclusive; overnight windows
belong to the starting day. Equal times mean 24 hours. Gaps/overlaps and invalid
numbers/times are rejected. Holiday/seasonal changes need a reviewed replacement
configuration; no unprovided holiday contract is assumed.

The Thermann device clock is separate. The owner reports it requires manual
DST adjustment. Compare it with the dashboard's current Hobart time, then record
the check date (YYYY-MM-DD) and reference clock verification. A DST transition
since that date, an old/future/unknown date, or an unverified clock produces a
visible reminder. No device clock is read or set through the API.

## Simple temperature and timing decisions

The energy estimate is `315 × 4.186 × temperature rise / 3600`, approximately
**0.3663 kWh/°C** or **7.33 minutes/°C at 3 kW**. Add the configured heating
allowance, initially **30 minutes**, only when a temperature increase is needed.
This is a planning estimate from bottom temperature, not measured tank energy,
element consumption or a guarantee of whole-tank conditions.

- **Before 07:00:** use the editable morning threshold, initially **40°C**. At or
  above it, recommend no additional morning heating, even if the native programme
  permits heating. Below it, estimate only the rise to that threshold plus margin
  and reserve off-peak time to finish by 07:00. **Never send or propose a 40°C
  storage setpoint.** Manufacturer thermostat/hygiene protections remain native.
- **Daytime:** plan towards **70°C** (editable 65–70°C modelling range). On
  weekdays finish before the actual evening peak: 17:00 Hobart in summer, 16:00
  in winter. Show the nominal 16:00 household comfort reference separately;
  neither the tariff clock nor device clock is silently changed to match it.
- **Weekends:** no evening peak is invented. Use 16:00 as the household comfort
  goal with solar opportunities and economical off-peak backup. After the day's
  storage deadline the next primary goal is morning comfort; this initial planner
  does not continuously maintain 70°C or add a separate late-evening top-up policy.
- **Solar:** require fresh adequate net export (3 kW plus configurable headroom,
  initially 0.3 kW) across a configurable observation hold, initially **10 minutes**.
  Low export, missing/stale reports, a large sample gap or restart resets the hold.
  Identical old reports cannot grow it. This is sampled evidence, not proof there
  were no fluctuations between samples. It does not switch the heater.
- **Wait versus start:** reserve a full grid fallback independently of forecasts.
  On equal-price grid periods, use the latest suitable off-peak slots to leave
  room for solar. Sustained surplus can recommend a bounded early opportunity
  (initially 15 minutes). Once the full fallback start is due, recommend heating
  rather than waiting indefinitely for solar. Comfort takes precedence when there
  is insufficient off-peak time; expose any unavoidable shortfall or peak use.

The model always uses a full **3 kW on/off load**. A solar/grid fraction describes
where that energy could come from, not modulated element power. Current confirmed
surplus is projected only over the short configurable opportunity window and is
labelled an assumption, never a whole-day forecast. Qualified net-export forecasts
remain optional pure-engine/scenario inputs; no live PV-to-surplus forecast guess
or new forecast dependency is required. A future forecast never moves the full
backup reservation later. Forecast energy/cost estimates are not guarantees.

Cost includes import plus foregone export compensation. The optional comparison
uses the same scheduled energy at today's rate, **not measured savings against
native Schedule**. Unserved energy is a shortfall, never a saving. Fixed supply
charges, showers and future draw-off are not invented. Reliable supervised
heating observations can later refine the time allowance; no automatic learned
power/reserve sensor is created from sparse mixed-use samples.

The thermostat's approximate 8°C hysteresis remains authoritative. The dashboard
warns when a requested storage target might not initiate heating from the current
reading. A software estimate does not bypass it or prove an energised element.

## Native settings, failures and actual control

Reference defaults remain weekdays ≈04–08 / 11–17, weekends ≈06–22, target 70°C
and T-Comfort 10°C. They are reference settings, never downloaded or written.
Schedule permission is not actual element power. The native programme can still
heat while the shadow planner recommends none; no real savings are claimed.
T-Comfort is not the optimisation architecture or useful reserve at 10°C.

Missing/stale/restored inputs, unhealthy cloud, or unexpected mode/target changes
block new plans and expose warnings. Planner setup/reload waits for a new normal
cloud poll rather than requesting one. Default client poll age is 45 minutes and
grid age 120 seconds; report limits stay editable. Fresh cloud-read time is still
not a verified device sample timestamp. No unverified Heating bit is decoded.

The owner accepts manual recovery after serious communication failures. Always-
successful automatic Schedule restoration is not a mandatory design requirement.
Actual start, stop/park, power resume, protection retention and owner recovery still
need qualification before execution is added. Manual at 65–70°C can keep heating
indefinitely; it is not a solar pulse. A native Schedule handback can also keep
heating inside its windows. No factory reset or safe API Off/On contract is invented.
See [control capabilities and recovery](CONTROL_AND_RECOVERY.md) and the
[supervised qualification sequence](SUPERVISED_VALIDATION.md).

## Cloud accounting

This planner adds **zero cloud requests**. 30-minute polling is about 48 cycles
per day per heater, not necessarily 48 requests. The owner observed 4→7 attempts
from status → token refresh → replay. Repeating that pattern gives roughly 144
HTTP attempts/day, plus discovery, login, errors and other clients. This is not a
vendor quota, upper bound, reset policy or confirmed server consumption.
The existing lifetime counters and safe categories are shown as local attempts;
planner observation restarts do not reset the bridge ledger or authentication.
No proactive token refresh, budget reset or new quota-management system is added.

## Later installation — owner approval required

1. Review PR #9 and back up HA. This branch has not been merged or deployed.
2. Copy only `custom_components/thermann_shadow` into the matching
   `/config/custom_components/thermann_shadow` folder. No bridge update is needed.
3. Restart HA once and add Thermann Shadow Planner from Devices & services. Use
   Configure to review entity selectors, confirmed tariff/meter defaults, morning
   and storage targets, margins and native clock reference. Keep heater commands
   and on-demand refresh disabled; do not change authentication generation.
4. Wait for a fresh normal bridge poll. Add `dashboard.yaml` as a separate manual
   dashboard. The Hot water view contains essentials; Diagnostics holds details.
   Check entity IDs against your registry in case prior naming added suffixes.
5. Observe shadow recommendations and data-age warnings only. No automation should
   consume these outputs as heater commands. Remove the integration to cancel its
   local timer/entities; no heater handback is needed because it never owned it.

Actual owner installation, visual dashboard rendering and owner-exported historical
replay remain untested. Isolated CI uses real HA Core config/options/sensor/reload
and unload paths, alongside all bridge/native/Supervisor regressions. The replay
command `python tools/replay_shadow.py shadow_controller/scenarios.json` is fully
local; bundled samples are synthetic, partly based on owner-reported observations.
Use de-identified numeric history only; no credentials or response bodies.

Before a separately approved live-control trial: confirm device-specific Manual,
stop/resume and readback behaviours, the chosen owner recovery route, bounded
request/confirmation policy and manufacturer protections. No extra physical probe
or complex thermal model is required to install this read-only component.
