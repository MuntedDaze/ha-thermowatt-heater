# Installation and commissioning

Historical PR #34 procedure. Use the [current owner plan](../final-integration/INSTALLATION.md)
for the integrated candidate, including HA-default IANA zones and no-solar setup.

For the unmerged 1.3.14 / 0.10.0 candidate. These are future owner procedures,
not commands executed by development. Review [upgrade and rollback](UPGRADE.md)
before changing a working system. No hardware commissioning or automatic-control
enable has been performed for this candidate.

## Read-only setup

1. Check compatibility in [the capability guide](README.md). Arrange appropriate
   qualified electrical work if adding a CT; the software never operates a CT
   relay or modifies mains wiring.
2. Install MQTT/Mosquitto and the MQTT integration on Home Assistant OS. Add
   `https://github.com/MuntedDaze/ha-thermowatt-heater` as an add-on repository
   only when an approved release is available there. The unmerged candidate is
   not automatically available from main; do not run a second bridge to try it.
3. Configure **Thermann Hot Water** using private add-on options/secrets. Keep
   `cloud_enabled: false`, `commands_enabled: false`, `command_policy: automation`
   and `auth_retry_generation: 0` until the owner deliberately authorises cloud
   access. One bridge per account. See [bridge options](../../thermowatt-heater/DOCS.md).
4. When separately authorised for read-only cloud access, verify the account
   with the vendor, deliberately enable cloud access and permit one authentication
   generation. Confirm status/health and the actual device serial. Failed login
   locks persist; repeated restarts are not a recovery strategy. Do not copy
   credentials or tokens into issues or test fixtures.
5. From an approved controller revision, copy only
   `custom_components/thermann_shadow` into `/config/custom_components/`, then
   restart HA once. Add **Thermann Controller** via Devices & services. The five
   required bridge mappings are your water heater, vendor mode, successful poll
   timestamp, cloud health and persistent request-attempt counter. Select actual
   entities; no household IDs are preselected. Grid, solar, house, forecast and
   dedicated circuit sensors are optional mappings.
6. Leave **Automatic heater control** off. Inspect the policy and diagnostic
   telemetry first. Installing the integration is not command commissioning.

## Useful settings

Configure → **Preferences** contains Everyday and Advanced settings; **System**
holds topics, verification and bounded technical controls. Entity mappings have
their own **Sources** page. Native HA setting entities show their explanation,
current/recommended/original value and whether restore preserves them. Changing
control-critical values while automatic control is active is refused; disable
control first. Restore does not reset mappings, tariffs, verification, command
guards or the new target/peak/boost decisions.

| Setting | Default / validation |
|---|---|
| Overnight baseline temperature | 45°C; supported choices 45 or 62 |
| Normal weekday storage temperature | 62°C; supported choices 62 or 70 |
| Optional solar storage temperature | 70°C; supported choices 62 or 70 |
| Target ordering | baseline ≤ normal ≤ boost; equal roles mean one physical state |
| Preferred completion before peak | 30 minutes; 5–120 |
| Heating during peak periods | Never schedule heating during peak; alternative Verified solar-only heating |
| Enable optional solar boost | On, but unavailable without qualified measurement; may be disabled independently |
| Tank capacity / nominal element power | Illustrative 315 L / 3 kW; supported planning ranges 50–500 L / 2–3.6 kW |
| Useful fraction of extra heat | 0.9 assumption; 0–1; lower if extra storage is unlikely to be used |
| Minimum boost benefit | AUD 0.10 per opportunity plus AUD 0.02/kWh margin; includes foregone feed-in and standby allowance |
| Tariff rates, periods and clock | Must be checked against the user's actual contract before tariff verification |
| Grid direction verified / tariff verified | Both false on a fresh install |
| Four-state commands qualified | False; requires separately authorised supervised qualification |

Only 45/62/70 are bridge-supported Manual values. A selector does not prove
hardware support. The 12-hour Override remains fixed at 70°C. Set normal and
boost both to 70 only if deliberately retaining the previous weekday target.

The supplied Aurora-like weekday schedule/rates are an **unverified example**,
not an appropriate tariff recommendation for a new user. `standard` means fixed
AEST (UTC+10); `local` currently means Australia/Hobart with DST, not arbitrary
HA time zones. Other tariff-clock zones are not qualified in this scoped project.
Use the existing custom-period JSON form for supported schedules, with days
0=Monday to 6=Sunday, complete coverage and no overlaps. Verify boundaries at DST
and weekends. The tariff verification switch alone cannot check your bill.

Existing forecast-assisted-control commissioning requires **Use published
forecasts** enabled before automatic activation. This is a retained feature
gate, not permission to trust unavailable forecasts. Valid PV and household-load
forecasts need generation timestamps; see [FORECAST_SETUP](../../shadow_controller/FORECAST_SETUP.md).
If actual forecasts are missing or expire, required weekday heat conservatively
waits until the latest start, with a persistent-outage alert; optional decisions
still require measured solar and their economics. CT-free operation does not
require a grid meter for essential heat, and a forecast outage does not stop the
cloud/tariff-based required fallback.

## Optional generic circuit measurement

Map `heater_power` to the meter's **own exclusive hot-water channel active power**,
in W or kW. Map `heater_energy`, if available, to its raw cumulative Wh or kWh.
Never map `sensor.em_hot_water_power` or `sensor.em_hot_water_energy`: these
dashboard wrappers can alter sign, timing or the energy basis. The controller
and Fable's package each read the same raw entities independently.

Before recording `entity_id|W` or `entity_id|kW` under **Commissioned hot-water
power entity and unit**, a qualified person/owner must independently verify the
circuit identity, sign, units, normal draw, low/zero draw, report cadence and
outage recovery. This is a commissioning record, not automatic sensor discovery.
Changing the mapped entity clears it; changing units invalidates it.

Observe steady zero for longer than two minutes and a normal heating run. The
sensor must provide genuine new reports within 120 seconds even when the value
does not change. A meter or HA integration that suppresses identical reports
must have its actual reporting behaviour resolved before solar control is used.
Do not use `abs()`, stale-value caching, a heartbeat template or nominal watts
to conceal sign/outage/cadence failures. Boot/restored/future reports are rejected.
Raw power remains signed in diagnostics; optional cumulative energy is not
authority for physical ON/OFF or solar dispatch.

Leave the mapping and verification empty for CT-free use. A previously mapped
meter failing is a fault, not a conversion to CT-free mode. Do not remove a
commissioned mapping merely to dismiss its outage notification; diagnose it,
or deliberately reconfigure the installation while disabled. Optional oven and
air-conditioning CT channels never affect hot-water qualification.

## Commissioning with automatic control off

Check read-only cloud receipts against the app, reported mode/setpoint/temperature,
status age, health, persistent request accounting, your actual MQTT device topic,
tariff and sign. Observe sunny/cloudy/zero/outage cases in shadow mode. Verify
**Heating during peak periods**, measurement mode and boost-enabled telemetry.
The default no-peak policy should want OFF ahead of every configured peak,
regardless of forecast or export. This is a desired state while disabled; no
command has been sent.

Only after separate owner approval should a supervised hardware plan test the
new supported states and exact-prior transitions, including OFF↔62, 45↔62,
62↔70, protective OFF, return to baseline, an intervening app change and delayed
confirmation. Check observed cloud readback and independent physical measurement
where available; a zero reading alone does not confirm the cloud command. Native
protections must remain untouched. Stop at a refusal, unexpected state, lockout
or uncertainty; do not retry a POST blindly. Record no private serials/tokens in
public commissioning evidence.

The new **Four-state commands qualified (1.3.14)** flag is intentionally false
even on an upgrade with three-state qualification. Do not set it just to clear
a commissioning warning. Activation also needs the actual advertised bridge
payload, topic binding, enabled commands, healthy auth/status, persisted accounting
and budgets. A flag cannot bypass those guards. On activation or restart the
controller waits for a new inspection before a fresh decision; it does not replay
an old intent. Do not enable automatic control as part of this development task.

## Troubleshooting and manual recovery

| Symptom | Meaning and response |
|---|---|
| `four_state_commands_not_qualified` | New hardware qualification is absent. Keep automation off; review the supervised plan. |
| Bridge lacks advertised 62°C payload | Confirm approved bridge version; never fabricate its diagnostic allowlist. |
| `meter_fault`, stale/ambiguous power | Check the raw meter, direction, units and genuine steady-value reports. Optional heating is unavailable. |
| CT-free physical state unknown | Expected. Cloud Manual/OFF and nominal power are not physical verification. |
| Forecast unavailable | Required heating uses the conservative latest-start fallback; investigate generation timestamps/mappings. |
| `peak_lockout_unverified` | OFF has not been confirmed. Check owner state, cloud/auth, bridge and budgets; do not assume zero consumption. |
| Owner override/hold | An app change is protected. Inspect it before explicitly resuming automation. |
| 62°C requested but probe lower | Native hysteresis, losses, draws or delay can explain it. The setting is not target achievement or shower-volume evidence. |
| Auth lock or HTTP 429 | Leave the lock intact; fix the cause and follow the bridge's deliberate recovery procedure. |
| Command not confirmed | It was sent at most once. Inspect the app/state before any new authorised action. |

Turning **Automatic heater control** off sends no heater command; the current
appliance setting can remain active. For manual recovery, disable automation
and deliberately select the appropriate vendor-app mode/setpoint for the
installation, following the appliance instructions. Stop bridge commands too if
needed. The vendor's Schedule is an owner choice, not an automatic fallback.
The 12hr Override is a real 70°C request when enabled; it may heat during peak.
Cancelling it returns planning to the ordinary policy, subject to the usual
guards. Review [rollback](UPGRADE.md) before returning to an older bridge.
