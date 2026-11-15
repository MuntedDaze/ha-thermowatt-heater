# Thermann hot water for Home Assistant

Use cheaper electricity for your hot water, with a dashboard that explains the
plan. The controller prepares normal storage when it is needed and can avoid
unnecessary extra heating. With a commissioned hot-water meter, it can also use
worthwhile surplus solar for extra storage. Savings depend on your demand,
electricity contract and heater; they are not guaranteed.

**Development candidate: bridge 1.3.16 / controller 0.12.0,
[draft PR #36](https://github.com/MuntedDaze/ha-thermowatt-heater/pull/36).** Unmerged and uninstalled.
Public distribution is deferred. Automatic heating, adaptive polling and learned
planning require independent review and separately approved commissioning.
Nothing in this development has operated the owner’s heater.

## How the parts fit together

| Part | Plain-language job |
|---|---|
| Home Assistant | The home computer that brings readings, preferences and the dashboard together |
| Thermann cloud bridge | One add-on that reads the Thermann service and sends only guarded, enabled commands; it tracks requests and confirms results |
| Intelligent controller | Chooses when normal hot-water storage is needed and compares permitted heating opportunities using prices, forecasts and local measurements |
| Dashboard | Seven read-only pages showing the heater, its plan, energy/cost estimates, learning, cloud requests and problems |

The native heater thermostat and protection remain in charge of the element.
An app change pauses automation when observed. Commands need a fresh matching
prior state and actual cloud confirmation; an unknown result is not blindly
repeated. **Cloud OFF is a software command, not proof of zero electrical power.**

## What equipment is needed?

You need a compatible Thermann Smart Electric heater/cloud account, internet,
Home Assistant OS and its MQTT broker/integration. MQTT is the local message
service joining the bridge and controller. One bridge per account and one
heater/controller entry are supported. Other heater models need compatibility
checks; entering their tank size does not qualify them.

Solar, GoodWe, EMHASS forecasts, circuit meters and the dashboard are optional.
EMHASS predicts solar generation and household use; it does not command the
heater. Basic tariff heating works without solar or EMHASS.

A dedicated CT is a circuit-power meter, such as a suitably installed Shelly,
that measures the heater separately. Qualified electrical installation and sensor
commissioning are required. Any validated Home Assistant exclusive-circuit
W/kW sensor can be used; it is not restricted to Shelly.

## What works before the CT is installed?

Overnight baseline, required weekday storage, tariff-based timing, peak lockout,
owner protection and guarded dynamic polling all work without a CT. Available
verified grid export and forecasts can help choose economical **required off-peak** heating. Nominal tank size/power provide estimates only.

Without a CT, electrical ON/OFF and an exact completion clock remain unknown.
“Continuous heating time estimate” is a conditional duration, not proof the
element is on or a promise of ready water. Optional solar-only boost stays
unavailable until dedicated measurement is commissioned. A failed previously
commissioned meter raises a fault; missing readings never become measured zero.

## Heating choices you can change

| Everyday choice | What it means |
|---|---|
| Baseline temperature | The permitted night/weekend thermostat setting |
| Normal storage temperature | The required weekday storage target |
| Optional solar temperature | Extra storage only when enabled, measured and economical |
| Heating during peak periods | Never, or verified solar-only subject to every safeguard |
| Enable optional solar boost | Independent on/off choice; required heating still works when off |
| Electricity plan and clock | Your verified retail rates/windows, household time zone and whether the contract follows daylight saving |
| Storage ready time | A weekday deadline when there is no afternoon tariff peak |

The owner’s proposed example is 45°C baseline / 62°C normal / 70°C optional boost.
Fresh setup initially selects 62°C baseline/normal pending compliance checks.
**45°C is not a universal storage-temperature recommendation.** Follow the
manufacturer’s instructions and applicable storage hygiene/plumbing requirements.
The selectors are limited to supported 45/62/70 roles; arbitrary temperatures
cannot be sent. A setpoint does not prove the whole tank reached it or guarantee
shower volume. The separate 12-hour Override is a real 70°C request and may heat at peak.

Flat-rate, time-of-use, shoulder, multiple daily/weekend, midday-discount and
month-based seasonal windows use one tariff model. Enter **retail contract**
prices, not a network tariff assumed to be your bill. Advanced demand/tier,
conditional-free and controlled-load billing remain unsupported.
[Tariff configuration and limits](docs/final-integration/TARIFFS.md).

## How polling saves requests

Local readings and forecasts are checked without calling Thermann every minute.
Fixed polling defaults to 30 minutes. Optional event-aware polling recognises a
confirmed quiet baseline/OFF period, checks before real decisions, and reuses
recent observations where command safeguards permit. Temperature-sensitive
planning returns to half-hour observations; lease loss uses the original fixed
fallback. It does not lengthen the bridge’s 60-second command-prior rule or skip
confirmation.

A separate default-off permission allows longer quiet checks. You choose a
healthy-cloud owner-change check bound of 30–90 minutes. Longer intervals save
requests but delay detecting app changes; brief changes can be missed. Outages
can delay detection further. Temperatures still expire after their normal
freshness limit, even during a permitted quiet hold. The existing request-driven
authentication heuristic is unchanged; no vendor session lifetime is assumed.

In the synthetic week, a 60-minute quiet limit used 447 versus 713 requests CT-free,
and 493 versus 740 with CT, preserving fixed-30 cost and target outcomes. The
persistent app change was detected after 45 versus 15 minutes in that example.
These are simulated trade-offs, not measured household savings.
[Polling evidence and recommendations](docs/pre-review/POLLING.md).

## What it learns and what you see

With reliable circuit measurements, the controller records heating energy,
duration, temperature rise and quality separately for each target. It tests
rates on later days excluded from fitting. Learned planning stays off until
sufficient clean sessions, held-out accuracy, hardware qualification and explicit
enablement all pass. Nominal planning remains the fallback. One bottom probe
cannot reliably identify whole-tank heat, water use or every extra boost’s value.

The seven dashboard views are Overview, Hot water, Costs, Appliances, History,
Energy and Health. They show requested versus reported temperatures, plans,
measurement availability, conditional estimates, actual/shadow polls, request
budgets and faults. The dashboard never controls the heater. CI checks HA schemas, entities and
templates; desktop/mobile appearance still needs visual review.

## Install, stop or get help

Start with [Jacob’s complete CT-free installation guide](docs/pre-review/OWNER_INSTALLATION.md)
for the existing Proxmox/HAOS, Thermann 315 L, GoodWe/HK1000, EMHASS and fixed-AEST
Aurora 93 system. It covers verified backups, exact reviewed files, guarded
**in-place** staging of the same stopped bridge, controller/dashboard installation,
entity mapping, supervised commissioning, request measurements, later Shelly and
recovery. Adding the unmerged branch URL is not an in-place upgrade.

Turning **Automatic heater control** off sends no OFF command: the appliance’s
current setting can remain active. Use approved manual operation during recovery.
Unconfirmed OFF is an unverified lockout, not a claim of zero consumption. Preserve
authentication locks and private backups; do not retry by restarting repeatedly.

- [Focused completion/review handoff](docs/pre-review/HANDOFF.md)
- [Development checkpoint](docs/pre-review/PROGRESS.md)
- [Dashboard mapping and saved-statistics reports](energy_monitoring/README.md)
- [Learning gates and limitations](docs/final-integration/LEARNING.md)
- [Bridge options and authentication guards](thermowatt-heater/DOCS.md)

Previous tested draft PRs remain untouched, including PR #35 at 8d2b1e4.
No merge, deployment, live authentication, heater operation, public release or
licence selection is part of this work. This unofficial project is not affiliated
with Thermann, Thermowatt, Reece or Ariston. Existing redacted security findings
remain an owner task before any future distribution.
