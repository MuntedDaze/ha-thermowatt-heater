# Thermann Shadow Planner 0.1.0 — Phase 2A review candidate

Separate custom Home Assistant integration, not a new Thermowatt bridge version.
The bridge remains **1.3.8**. No automatic installation, merge or deployment.

## Hard boundary

This component only reads existing HA states and publishes its own sensor states.
There is no HTTP client, MQTT publish, heater service, command action, refresh
trigger, authentication setting or write to the native heater. No option removes
this boundary. EMHASS is not required. The existing bridge continues 30-minute
polling / minimum 60-minute error cooldown, commands and demand disabled.

Plans are counterfactual advice while native Schedule still owns the heater.
`shadow_heat_now` is a reason to inspect a **hypothetical** window, not proof of
element power or an executed action. The dashboard contains only sensor cards
and a navigation button. Never attach an automation to these outputs in Phase 2A.

## Later owner installation only

1. Review this PR and make a Home Assistant backup first. Copy only
   `custom_components/thermann_shadow` to `/config/custom_components/thermann_shadow`.
   No HACS install hook, bridge replacement or credentials are involved.
2. Restart HA once for component discovery. Add **Thermann Shadow Planner** from
   Settings → Devices & services → Add integration. Defaults are the owner's
   supplied entity IDs; select/edit them. No pairing or cloud login occurs.
3. Open its **Configure** action to edit mappings, assumptions and tariffs. Leave
   meter/tariff validation flags OFF until independently confirmed. The default
   zero prices and flat full-week off-peak period are placeholders, not Aurora
   contract data. Leave native Schedule, T-Comfort, bridge flags and generation
   unchanged. Any reference setting here changes only the scenario, never the tank.
4. Wait for a new normal bridge poll after planner setup/reload. Cached readings
   and retained pre-start poll timestamps cannot qualify a fresh plan. The local
   timer runs every five minutes; grid changes do not trigger cloud requests.
5. Create a separate manual YAML dashboard from `dashboard.yaml`. It uses only
   built-in cards. Verify entity IDs in your entity registry; collisions/renaming
   can add suffixes. Edit dashboard references if necessary, including vendor mode.
6. Remove the integration to stop its timer/entities. Remove the custom folder
   and optional dashboard to uninstall. No heater handback is necessary because
   it never acquired control. Your original MQTT entity identities remain intact.

Actual owner-HA installation and Lovelace rendering have not been exercised by
the agent. CI checks real HA Core setup, config/options flows, sensors and unload
inside isolated images; native bridge/Supervisor checks remain in place.

## Measurements, assumptions and estimates

The defaults map `water_heater.home_boiler_home` attributes `current_temperature`
and `temperature`, even when its HA mode/state is Unknown. Schedule comes from
`sensor.home_boiler_home_vendor_mode`. The unverified Heating sensor is never
read. HA must expose temperatures in °C; unexpected units block planning.

GoodWe/HK1000 defaults are the owner's PV, house load and meter-active-power
entities. Signed grid power is displayed unchanged apart from explicit W→kW
normalisation. The **separate derived net-export value** uses the configured
sign: export-positive by default, provisionally based on 2322 W PV − 821 W house
= +1501 W meter. A load test remains required. The sign option is editable; it
is not silently inferred, inverted or calibrated. Only measured net export
influences solar opportunities. PV/house values are display-only. Cumulative
import/export mappings are retained as reference inputs, not assumed heater use.

The 315 L uniform-tank scenario uses `315 × 4.186 / 3600 = 0.366275 kWh/°C`,
with ideal heating at 3 kW plus an explicitly configurable time allowance
(default 30 min). That is **not measured stored energy, remaining usable water,
actual electrical consumption or a stratification model**. At 63→65°C the ideal
energy is about 0.733 kWh; 40→65°C is about 9.16 kWh before the allowance. A 40°C
bottom reading never becomes a storage target or hygiene permission.

Morning comfort stays **07:00**, evening comfort **16:00**, in Australia/Hobart.
An earlier confirmed afternoon peak can advance the planning deadline, but both
comfort and peak timestamps remain visible separately. Weekends follow the
configured tariff; no holiday pricing is assumed. Future plans cover the next
comfort requirement, not a guaranteed multi-day demand forecast.

The planner allocates hypothetical minutes before the deadline: fully available
net solar first, then lowest estimated opportunity cost, allowing necessary grid
import if cheap slots cannot meet the modelled requirement. Costs include
foregone export compensation. A difference compares the same **scheduled**
model energy at the current import rate, not measured savings against native
Schedule; energy that cannot fit is a shortfall, never a saving.

Live HA planning uses only the **current minute's** measured export; it never
extrapolates today's sunny reading across future hours. Qualified net-export
forecast scenarios are supported by the pure engine/tests, but no forecast
entity adapter or PV-to-surplus guess is enabled in this first release. Without
that input, future windows use grid-price assumptions and explicitly warn that
no net-surplus forecast is available. The five-minute dashboard cadence is not a
freshness or comfort guarantee. These fragmented hypothetical slots are not an
executable schedule or thermostat/command policy.

## Tariff configuration

Enter **AUD/kWh**, not cents, from the actual contract: off-peak, shoulder, peak
and export compensation. The JSON period field covers every minute of all seven
days exactly once. Days are Monday=0 through Sunday=6; start inclusive/end
exclusive; an overnight window belongs to its starting day. Equal start/end
means a whole day. Gaps/overlaps, invalid days/times, nonfinite values and out-of-
range settings are rejected. `local` follows Hobart DST; `standard` is fixed
UTC+10, only if that is what the contract requires. Rates need no published
Aurora values. Reconfigure after a contract change; a settings reload waits for
fresh normal polling instead of requesting it. Public holidays/seasonal contract
changes need a reviewed replacement configuration; no automatic calendar exists.

**Synthetic example only, not the owner's tariff:**

```json
[
  {"days":[0,1,2,3,4],"start":"00:00","end":"07:00","kind":"off_peak"},
  {"days":[0,1,2,3,4],"start":"07:00","end":"10:00","kind":"peak"},
  {"days":[0,1,2,3,4],"start":"10:00","end":"16:00","kind":"off_peak"},
  {"days":[0,1,2,3,4],"start":"16:00","end":"21:00","kind":"peak"},
  {"days":[0,1,2,3,4],"start":"21:00","end":"00:00","kind":"off_peak"},
  {"days":[5,6],"start":"00:00","end":"00:00","kind":"off_peak"}
]
```

## Cloud budget and data quality

The planner adds **zero** requests of any category. It never sends on-demand
refresh, including during shortages, changing solar, restart or quota lockout.
For one heater, 30-minute background polling is approximately 48 cycles/day.
The owner observed 4→7 attempts between 14:33 and 15:03: status, token refresh,
status replay. If every cycle had that pattern it would be roughly **144 HTTP
attempts/day**, plus discovery, login, errors and any other devices/clients.
Neither number is a guaranteed bound, confirmed vendor consumption, allowance or
daily reset policy. Authentication/refresh security remains exactly the bridge's.

The UI shows local observed counter growth/rate since the planner's observation
start, and safe existing category totals (login/refresh/discovery/status/command/
confirmation) where available. It reports reset/incomplete accounting. It does
not restore a fictitious daily counter or include the official app. HA restart
starts a new observation window; the bridge's lifetime ledger stays untouched.

Required states must be valid, non-restored and reported after planner setup.
Grid readings default to a 120-second age limit; heater client polls to 45 min
(both configurable within tested bounds). Cloud health must be OK and a fresh
last-poll timestamp must be at/after setup. A new HA report of an old poll is not
a new sample. Client read freshness still does not prove device sample freshness.
Missing/stale data, cloud problems or unexpected native mode/target changes block
new plans. Intervention is latched for configuration review for the current
planner session. Reload is only a shadow re-baseline, never a control approval.

## Owner native fallback and T-Comfort

Reference defaults preserve the reported programme: weekdays approximately
04–08 and 11–17, weekends 06–22, Schedule target 70°C, T-Comfort 10°C. They are
not downloaded, saved back or verified by an API. The device clock/DST is
unverified. A separate reference sensor says whether a time lies within those
windows, never that the element is energised. The controller shows permitted
minutes before the next comfort deadline and warns when they cannot fit the
depleted uniform-tank scenario. At 3 kW, weekday 04–07 permits only 9 kWh before
07:00; weekend 06–07 permits only 3 kWh. The comfort-first schedule is a safety
net intention, not proof that any depleted tank can recover in those windows.

The [newer manufacturer manual, printed p17/PDF p23](https://digitalassets.reecegroup.com.au/m/65539137e892f4b1/original/Installer-s-Manual-Thermann-Smart-Electric-Water-Heaters.pdf)
documents Schedule T-Comfort down to 10°C and possible heating outside programmed
windows, with approximately 8°C hysteresis. It excludes Holiday/Turn OFF. The
[older guide, p11](https://www.thermann.com.au/thermann-cms/files/Thermann-Smart_Electric-Owners_Guide.pdf)
instead gives a 20°C minimum, so version/firmware applicability matters. At the
owner's 10°C setting, this planner grants **no useful comfort reserve**. A higher
setting could provide a Schedule-only minimum but could also consume peak-rate
electricity outside the programme; this is an inference, not a proposed change.
Neither source establishes this installation's Manual fallback or a reversible
API power switch. No T-Comfort, Schedule, power or hygiene setting is changed.

See [supervised qualification](SUPERVISED_VALIDATION.md) before considering any
later write. Native Schedule remains the baseline; unattended control stays NO-GO.

## Still needed from the owner

- Actual bill/contract import rates, export compensation, weekly/seasonal periods,
  holiday rules and DST basis. Weekend off-peak intention is recorded, not a rate.
- Independent non-heater load-test evidence for signed grid power and updates;
  source sample cadence/lag, especially the HK1000 and cloud temperature.
- Precise saved weekly programme and device clock/DST confirmation; the current
  approximate times and 10°C T-Comfort are sufficient reference defaults.
- Household demand/flow and inlet-temperature observations to calibrate usable
  reserve and losses; no bottom-only model can guarantee shower availability.
- Model-specific approved Manual limits, confirmed hygiene configuration and a
  supervised independent recovery route before a separate control-test request.

## Offline historical/scenario replay

`python tools/replay_shadow.py shadow_controller/scenarios.json` reads a local
numeric snapshot file and prints hypothetical plans. It performs no network or
HA access. Use the same JSON schema for a de-identified owner-exported history;
only times, temperature/target, signed grid watts, vendor mode, cloud health and
poll age are needed. Include actual confirmed tariff options, or leave validation
false and costs unavailable. Never include passwords, tokens or cloud payloads.
The bundled trace is **synthetic**, with two owner-reported observations anchored
to a test date, not acquired historian data. The real-HA adapter additionally
latches intervention and requires post-restart reports; replay snapshots alone
do not qualify those lifecycle/control gates. An actual owner-history dataset
has not been supplied or tested yet.

## Implementation references

HA [config entries](https://contributors.home-assistant.io/core/integrations/config-entries/),
[sensor entities](https://contributors.home-assistant.io/core/entities/sensor/) and
[event helpers](https://contributors.home-assistant.io/core/integrations/events/).
See CHANGELOG.md for the independent component version. No bridge release bump
is needed because the add-on source, options and MQTT discovery are untouched.
