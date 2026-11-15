# Thermann hot water for Home Assistant

This project helps a supported Thermann Smart Electric water heater use cheaper
electricity. It shows the heater in Home Assistant, plans the household’s normal
hot-water storage, and can store extra heat when measured solar would make that
worthwhile. Home Assistant is the home computer that combines the heater,
electricity readings and dashboard.

**This is an uninstalled development candidate: bridge 1.3.15 / controller
0.11.0, [draft PR #35](https://github.com/MuntedDaze/ha-thermowatt-heater/pull/35).**
Public distribution is deferred. Nothing here has been deployed or enabled on
the heater. Automatic control, adaptive polling and learned planning require
separate commissioning; new installations start with control disabled.

## Equipment

You need a compatible Thermann heater and cloud account, internet access, Home
Assistant OS on supported amd64/aarch64 hardware, and its MQTT broker/integration.
MQTT is the local message service connecting the add-on and controller. One
bridge per account and one heater/controller entry are supported. Other heater
models need compatibility checks; entering their tank size does not qualify them.

Solar panels, an inverter, EMHASS forecasts, circuit meters and this dashboard
are **optional**. EMHASS supplies predictions of solar generation and household
use. Basic tariff-based heating works without any of them. The current setup
is intended for an owner who can install an add-on and custom integration, with
help if needed. It does not modify wiring or replace a licensed installer.

## What decides when to heat

There is one heating plan, with four possible requests:

| Request | Purpose |
|---|---|
| OFF | Ask routine heating to stop before a configured expensive peak |
| Baseline | Maintain the selected thermostat setting during permitted nights/weekends |
| Normal storage | Prepare required weekday storage before peak, or a chosen ready time on flat-rate days |
| Solar boost | Optional extra storage if enabled, measured solar is qualified and the expected benefit passes the safeguards |

The owner’s worked example uses 45°C baseline, 62°C normal and 70°C boost.
**45°C is not a general storage-temperature recommendation.** Fresh setup starts
with 62°C baseline/normal awaiting appliance and local compliance checks. The
allowed role choices are limited to bridge-supported 45/62/70 values; arbitrary
setpoints cannot be sent. Follow the manufacturer’s instructions and applicable
storage, hygiene and outlet-temperature requirements with qualified advice.
Native heater protection remains in charge. A requested target is not proof the
whole tank reached that temperature or a guarantee of available shower water.

The controller compares heating now with available later opportunities. It uses
retail electricity prices, measured surplus solar, available forecasts, heating
time, a conservative loss allowance and the assumed usefulness of extra heat.
Using solar gives up export income, so solar heating is not automatically free.
Small benefits do not justify extra switching. Required heating has priority over
optional boosts, within the same safety and command limits. Simulations explain
the trade-offs; they are not a promise of household bill savings.

**Heating during peak periods** offers Never or verified solar-only heating.
Never takes priority over export and forecasts: required heating is planned to
finish beforehand and OFF is requested ahead of the boundary. **Enable optional
solar boost** is independent: it can be off, allowed only outside peak, or used
with verified solar-only peak policy. The separate 12-hour Override can heat to
70°C during peak. App changes pause automation until the owner resumes it.

## With and without measurements

Without a dedicated hot-water circuit meter, normal baseline and required
permitted storage still use cloud mode, setpoint, temperature and your tariff.
Nominal power and tank size give labelled planning estimates. Physical element
ON/OFF stays unknown, and optional solar boost is unavailable.

With a commissioned circuit-power sensor, the controller can verify element draw
and qualify solar opportunities. Any validated Home Assistant circuit sensor in
W or kW can be used; it is not limited to Shelly. Optional native energy readings
accept Wh or kWh. Both must come directly from the exclusive hot-water channel.
Signed power and genuine fresh reports matter, including unchanged zero readings.
A failed previously commissioned meter raises a fault and blocks optional heating;
it is never silently treated as zero or as a new CT-free installation.

The system records measured heating intervals, energy, temperature change and
quality separately for each target. It can evaluate heating rates on later days
that were not used for fitting. Learned planning remains disabled until sufficient
clean data, held-out error checks, independent hardware qualification and explicit
enablement all pass. Missing evidence uses nominal planning. A single bottom
probe cannot reliably identify water draws, tank-wide heat, standby loss or how
useful every extra boost was; those effects are not claimed as learned.

## Fewer cloud requests

The controller evaluates local readings without asking Thermann every minute.
The bridge alone handles cloud access, request accounting and confirmation.
Fixed polling defaults to 30 minutes. An optional real adaptive scheduler can
reuse recent reads and choose bounded intervals around important decisions,
without changing authentication backoff, budgets or command confirmation.

Adaptive scheduling defaults off on both sides. It is bounded to 15–40 minutes
with a verified CT and at most 30 minutes without one, inside the existing
freshness limits. Losing the controller’s scheduling messages returns to fixed
polling. Less polling can miss short app changes: a five-minute change was missed
in the week replay. Request reductions are scenario-dependent, not guaranteed;
[the comparison](docs/final-integration/SIMULATIONS.md) includes actual synthetic
HTTP counts and detection delays.

## Configure and see the result

During setup, select your real bridge entities; household sensor IDs are not
preselected. Choose your IANA time zone (initially Home Assistant’s zone), the
contract’s daylight-saving or fixed-standard tariff clock, rates and periods.
Flat-rate, editable weekday/weekend/shoulder and multiple daily windows, midday
discounts and month-based seasons use one tariff model. Prices must be verified
against your **retail contract**; network tariffs are not automatically your
retail prices. Advanced demand/tier/conditional-free products are explicitly
unsupported. See [tariffs and temperature choices](docs/final-integration/TARIFFS.md).

The optional seven-view dashboard shows the plan and reason, requested and
reported temperatures, measured power if available, grid/solar use, costs,
forecast/history, learning quality, next actual and shadow poll, request budget,
peak policy, measurement availability and boost choice. Costs use the controller’s
verified current price. Unmapped or expired measurements show unavailable, not
invented zeros. The dashboard never commands the heater. Actual HA schema,
entities and templates are tested; frontend appearance still needs owner review.

## Install, commission, stop or recover

There is no approved public release to install from main for this candidate.
After review and separate owner approval, use the
[installation and commissioning guide](docs/final-integration/INSTALLATION.md).
It covers backups, one bridge, controller setup while disabled, dashboard copy,
tariff/sensor checks and supervised qualification. Do not run a second bridge
or enable automation just to clear a warning.

Turning **Automatic heater control** off sends no OFF command: the current
appliance setting can remain active. Check the vendor app and follow the
appliance’s manual operating instructions. Cloud OFF is a software command,
**not proof of zero electrical consumption**. Native protection, manual
intervention and outages can still occur. Unconfirmed OFF is reported as an
unverified lockout, not a promise that the element is off. Cloud failures pause
control; commands are not blindly repeated. The guide includes troubleshooting
and [upgrade/rollback](docs/final-integration/UPGRADE.md).

- [Current capability and validation matrix](docs/final-integration/COMPLETION_MATRIX.md)
- [One Tasmania / Aurora 93 / 315 L / GoodWe / EMHASS household example](docs/dual-storage/HOUSEHOLD_EXAMPLE.md)
- [Learning evidence and safeguards](docs/final-integration/LEARNING.md)
- [Engineering interfaces and architecture](docs/final-integration/TELEMETRY.md)
- [Dashboard mapping and reports](energy_monitoring/README.md)
- [Bridge options and existing authentication guards](thermowatt-heater/DOCS.md)
- [Development checkpoint](docs/final-integration/PROGRESS.md)

Offline development uses `requirements-dev.txt`, pytest, Ruff, strict type checks,
compileall and Bash checks. CI also runs actual Home Assistant, native
amd64/aarch64 images with isolated MQTT/lifecycle tests, and Supervisor schemas.
All heater/cloud tests use synthetic inputs and blocked external networking.
Existing draft PRs #27/#32/#33/#34 remain recovery/review checkpoints.

This unofficial project is not affiliated with Thermann, Thermowatt, Reece or
Ariston. No licence has been selected. Historical credential findings remain an
owner review item before future distribution; see the
[existing redacted review](docs/dual-storage/PUBLIC_RELEASE.md). No release,
licence, history rewrite or credential rotation is part of this development.
