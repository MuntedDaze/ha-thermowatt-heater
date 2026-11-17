# Thermann hot water for Home Assistant

**Next development candidate: controller0.16.0 / bridge1.4.0.**
[Draft PR42](https://github.com/MuntedDaze/ha-thermowatt-heater/pull/42) contains
the new62°C override, solar-led weekend comfort, explicit Smart polling,
practical experimental CT-free setup and focused homeowner interface.
Use the reviewed commit and final successful checks, not a version string alone.

[Owner handbook](docs/next-major/OWNER_HANDBOOK.md) ·
[Existing-system upgrade](docs/next-major/OWNER_UPGRADE.md) ·
[Every setting](docs/next-major/SETTINGS.md) ·
[Dashboard and diagnostic report](docs/next-major/INTERFACE.md) ·
[Engineering evidence](docs/next-major/EVIDENCE.md).

Use cheaper electricity for your hot water, with a dashboard that explains the
plan. The controller prepares normal storage when it is needed and can avoid
unnecessary extra heating. After separate CT-free grid-only or circuit-meter commissioning, it can also
use worthwhile surplus solar for extra storage. Savings depend on your demand,
electricity contract and heater; they are not guaranteed.

**Existing owner installation:** The owner reported a working bridge, GoodWe
readings and EMHASS while testing in Shadow Mode. Check the actual installed
versions before updating. This candidate builds on controller **0.15.1** /
bridge **1.3.17** and prepares an in-place update to **0.16.0 / 1.4.0**.

[Current upgrade and commissioning guide](docs/next-major/OWNER_UPGRADE.md) ·
[Development checkpoint](docs/next-major/PROGRESS.md) ·
[Compatible data/control interfaces](docs/completion/INTERFACES.md).
No development test enables owner commands, automatic control, adaptive polling
or learned authority. Earlier draft/candidate notes are historical checkpoints.

## How the parts fit together

| Part | Plain-language job |
|---|---|
| Home Assistant | The home computer that brings readings, preferences and the dashboard together |
| Thermann cloud bridge | One add-on that reads the Thermann service and sends only guarded, enabled commands; it tracks requests and confirms results |
| Intelligent controller | Chooses when normal hot-water storage is needed and compares permitted heating opportunities using prices, forecasts and local measurements |
| Dashboards | Five focused Thermowatt pages with existing guarded controls, plus the independent seven-view whole-home energy dashboard |

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
element is on or a promise of ready water. Optional solar-only boost requires
either a commissioned dedicated heater circuit meter (CT) or the separately
configured experimental CT-free GoodWe grid-meter setup. Turning **Enable optional
solar boost** on alone does not start boosting: automatic control and all measurement,
solar surplus, cost, peak-policy and safety requirements must also be satisfied.
A failed previously
commissioned meter raises a fault; missing readings never become measured zero.

## Heating choices you can change

Open **Settings → Devices & services → Thermann Controller → Configure/settings**.
Choose **Hot Water**, **Electricity Tariffs**, **Solar & Meters** or
**Advanced/System**. Each field now explains what it does, its units and relevant
cautions. Everyday choices are separate from commissioning. Prices show cents
per kWh and forecast allowances show percentages. A guided day/time editor
handles custom electricity periods without writing JSON. Your saved household
settings and entity IDs are retained.
[Where to find each setting and how the forms work](docs/configuration/SETTINGS.md).


| Everyday choice | What it means |
|---|---|
| Baseline temperature | The permitted night/weekend thermostat setting |
| Normal storage temperature | The required weekday storage target |
| Optional solar temperature | Extra storage only when enabled, measured and economical |
| Heating during peak periods | Never, or verified solar-only subject to every safeguard |
| Enable optional solar boost | Independent on/off choice; required heating still works when off |
| Electricity plan and clock | Your verified retail rates/windows, household time zone and whether the contract follows daylight saving |
| Storage ready time | A weekday deadline when there is no afternoon tariff peak |

The owner’s agreed strategy is 45°C baseline / 62°C normal / 70°C optional boost,
with OFF during configured peak periods. The owner chose this after plumber
discussion; independent compliance has not been established by this project.
Fresh setup initially selects 62°C baseline/normal pending compliance checks.
**45°C is not a universal storage-temperature recommendation.** Follow the
manufacturer’s instructions and applicable storage hygiene/plumbing requirements.
The selectors are limited to supported 45/62/70 roles; arbitrary temperatures
cannot be sent. A setpoint does not prove the whole tank reached it or guarantee
shower volume. The separate **12hr Override 62°C** is a real 62°C request and may heat at peak.

Weekend daytime PV can open normal62 comfort storage with deliberate off-peak
grid assistance. This day latch avoids toggling with every cloud; sunset/end
settings return to baseline. Optional70 still needs stronger actual surplus
and economic checks. [How weekends and CT-free solar work](docs/next-major/OWNER_HANDBOOK.md#solar-and-weekends).

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

New explicit choices are **Smart — Recommended**, **Fixed30 — Compatibility**
and **Experimental minimum requests**. Existing installations retain earlier
choices until deliberately changed in both the App and controller. Healthy quiet
Smart nights may wait up to8 hours; Minimum up to12. Longer intervals delay
detecting app changes, and brief changes can be missed. Outages delay detection
further. Temperature still expires normally; a long quiet hold does not make it
fresh. Smart ordinary status reads reuse sessions with the existing bounded401
refresh/retry; command authentication preparation and confirmation remain guarded.
No vendor token lifetime is assumed. [Actual-worker comparisons and their limits](docs/next-major/EVIDENCE.md).

## What it learns and what you see

With reliable circuit measurements, the controller records heating energy,
duration, temperature rise and quality separately for each target. It tests
rates on later days excluded from fitting. Learned planning stays off until
sufficient clean sessions, held-out accuracy, hardware qualification and explicit
enablement all pass. Nominal planning remains the fallback. One bottom probe
cannot reliably identify whole-tank heat, water use or every extra boost’s value.

The existing seven whole-home views remain independent. The new Thermowatt
dashboard has Home, Controls, Heating preferences, Electricity and optimisation,
and Advanced and diagnostics. It separates reported and requested states,
measurement availability, estimates and faults. Native Configure forms provide
inline help and a **Copy diagnostic report** view: select all and copy once.
Standard authenticated JSON diagnostics are also available. Real HA desktop/mobile
frontend checks and screenshots supplement Python/YAML tests.
[Install the focused dashboard and copy a report](docs/next-major/INTERFACE.md).

## Install, stop or get help

Start with [Jacob’s complete existing-system upgrade guide](docs/next-major/OWNER_UPGRADE.md)
for the existing Proxmox/HAOS, Thermann 315 L, GoodWe/HK1000, EMHASS and fixed-AEST
Aurora93 system. It covers backups, controller0.15.1→0.16.0 and the existing
bridge1.3.17→1.4.0 in-place update, preserved credentials/guards/mappings,
owner-approved trials, request measurements and adding a CT later.
No duplicate add-on, uninstall or Supervisor cache manipulation is needed.

Strict peak OFF can leave the heater OFF if cloud/authentication/controller access
fails. A distinct warning appears after permitted heat has been wanted for30
minutes without restoration. It cannot restore heat without a working path.
A tested phone notification and manual recovery plan are commissioning items.
[Fault recovery and inactivity qualification](docs/audit-remediation/OPERATIONS.md).
New experimental choices explain their limits rather than pretending synthetic
tests qualify physical hardware or establish a vendor session lifetime.

Turning **Automatic heater control** off sends no OFF command: the appliance’s
current setting can remain active. Use approved manual operation during recovery.
Unconfirmed OFF is an unverified lockout, not a claim of zero consumption. Preserve
authentication locks and private backups; do not retry by restarting repeatedly.

- [Audit remediation/review handoff](docs/audit-remediation/HANDOFF.md)
- [Current development checkpoint](docs/next-major/PROGRESS.md)
- [Dashboard mapping and saved-statistics reports](energy_monitoring/README.md)
- [Learning gates and limitations](docs/final-integration/LEARNING.md)
- [Bridge options and authentication guards](thermowatt-heater/DOCS.md)

Previous tested draft PRs remain untouched, including PR #35 at 8d2b1e4.
This candidate remains a draft until final checks and separate owner merge
approval. Installation, live authentication, heater operation and automatic
activation also require separate owner approval. This unofficial project is not affiliated
with Thermann, Thermowatt, Reece or Ariston. Existing redacted security findings
remain an owner task before any future distribution.
