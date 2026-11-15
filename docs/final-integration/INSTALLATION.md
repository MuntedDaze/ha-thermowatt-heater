> Historical checkpoint: superseded for installation and current audit status.
> Use the [audit remediation handoff](../audit-remediation/HANDOFF.md) and
> [normal owner guide](../pre-review/OWNER_INSTALLATION.md). Supervisor cache
> staging is unsupported; preserve the owner’s agreed45/62/70 strategy.

# Owner installation and commissioning plan

Bridge 1.3.15 / controller 0.11.0, draft PR #35; uninstalled and unmerged.
These are future procedures for separately approved work. This development does
not authorise cloud access, authentication, real MQTT commands or heater operation.
Public distribution is deferred; a source branch is not an approved add-on release.

## Before changing a working system

1. Verify the reviewed commit and [completion matrix](COMPLETION_MATRIX.md).
   Keep the unchanged PR #27/#33/#34 recovery anchors and Fable #32.
2. Deliberately disable automatic control and inspect the vendor-app state.
   Disable sends no heater command. Resolve any pending/unconfirmed intent before
   changing versions; do not assume restart cancelled it.
3. Make and verify private recoverable backups of HA configuration/registry,
   config entries/options and `thermann_shadow` storage, plus the same add-on’s
   entire `/data`: options/credentials, tokens, auth guard/generation, request
   usage, command state and device configuration. Never upload these to GitHub.
4. Use one bridge for the account. Never start a parallel development bridge or
   use an owner HA, MQTT, Docker or Proxmox service as an offline test environment.

## Read-only installation, after separate approval

Use the reviewed source with the existing add-on installation/slug. The main
repository URL alone will not install this unmerged branch. An approved local
add-on build or future merged candidate must use the exact reviewed files; keep
the same private data and installation identity. Upgrade the bridge first, with
all cloud/command/auth-generation choices preserved. A fresh installation starts
with `cloud_enabled: false`, `commands_enabled: false`, authentication generation
zero and the normal `automation` command policy. Do not switch to `legacy` to
work around a refusal.

Only separately authorised read-only cloud access may verify the account/device.
A lock permits no retry until the cause and deliberate recovery are reviewed.
Never delete a guard, increment generations repeatedly or paste raw HTTP bodies
into troubleshooting reports. The existing [bridge guide](../../thermowatt-heater/DOCS.md)
explains its one-attempt authentication and command confirmation.

Copy the reviewed `custom_components/thermann_shadow` directory to HA’s
`/config/custom_components/`, retaining an existing entry if upgrading, and
restart HA once. Add **Thermann Controller** via Settings → Devices & services.
Choose the actual bridge water heater, vendor mode, successful-poll timestamp,
cloud health and persistent request counter. Fresh setup supplies no household
entity IDs. Leave **Automatic heater control** off.

## Household setup

Preferences has Everyday/Advanced settings, Sources has entity mappings, and
System holds qualification/topic/budget controls. Disable automatic control
before changing critical settings; invalid combinations are rejected atomically.
Restore preserves mappings, tariffs, qualification and critical technical choices.

| Setting | Fresh setup / checks |
|---|---|
| Time zone | HA’s configured IANA zone; choose the actual household zone |
| Tariff profile | Flat, rate zero/unverified placeholder; enter and verify the retail contract |
| Tariff clock | Local DST initially; select fixed standard if the actual contract requires it |
| Time-of-use | Editable full-week windows, prices, weekdays/weekends and optional months; no gaps/overlaps |
| Baseline / normal / solar boost | Initially 62 / 62 / 70; appliance/hygiene qualification still required |
| Supported selectors | Baseline 45 or 62; normal/boost 62 or 70; ordered baseline ≤ normal ≤ boost |
| Heating during peak periods | Never by default; verified solar-only is an explicit alternative |
| Enable optional solar boost | False; independent of peak policy |
| Use published forecasts | False; basic tariff control needs neither EMHASS nor solar |
| Tank / nominal power | Illustrative 315 L / 3 kW; enter actual values within supported 50–500 L / 2–3.6 kW ranges |
| Ready window without afternoon peak | Local 09:00 start, 16:00 ready minus completion margin, 21:00 baseline; editable |
| Four-state commands qualified | False until separately supervised OFF/45/62/70 transitions are proved |
| Send adaptive cloud scheduling plans | False; bridge also needs both adaptive flags false→explicitly qualified/enabled |
| Learned planning / hardware qualification | Both false; synthetic tests never supply real qualification |

The owner’s 45/62/70, Aurora 93, fixed AEST, GoodWe and EMHASS settings are one
[worked example](../dual-storage/HOUSEHOLD_EXAMPLE.md), retained on upgrade.
They are not new-user defaults. Verify storage hygiene, outlet temperatures and
manufacturer requirements for the actual installation. No arbitrary 60/65°C
command or unsupported heater is qualified by changing a planning field.
[Tariffs](TARIFFS.md) covers contract clocks, example JSON and unsupported billing.

## Optional measurement and dashboard

For CT-free operation, leave heater power/energy mappings and commissioning
identity empty. Physical element state stays unknown. Required baseline/storage
remain supported. Optional solar boost cannot use nominal/inferred watts.

For a dedicated circuit meter, map the **raw exclusive hot-water power** in W/kW
and optional raw cumulative energy in Wh/kWh. Do not map dashboard `em_` wrappers.
Independently verify circuit, polarity, units, draw, genuine steady-zero reports
within 120 seconds, outage/recovery and report timestamps before recording
`entity_id|unit` as commissioned. A heartbeat template or `abs()` does not prove
freshness/sign. Meter remap/unit/model changes invalidate qualification.
Previously commissioned meter loss must remain a notified fault; do not remove
its mapping just to hide the outage. AC/oven channels are independent.

The optional [monitoring guide](../../energy_monitoring/README.md) explains copying
the generated package and seven-view dashboard. Edit the map for the actual
installation, leaving absent grid/solar/household meters blank; regenerate and
check HA configuration before restarting. In combined mode prices come from the
controller; only the supply-charge helper is edited in Costs. Existing GoodWe
and appliance IDs are owner examples. Review actual entity IDs in HA; renamed
entities require remapping. Package install never enables heater control.

## Supervised sequence, each step requires owner authorisation

1. Observe disabled policy through weekdays/weekends, relevant tariff/DST
   boundaries, missing forecasts, cloud failures and optional sensor outages.
   Inspect requests/health and verify that tariffs and actual clock agree.
2. Confirm CT-free baseline estimates are labelled nominal/unknown and no optional
   boost is offered. Without solar/EMHASS there must be no artificial forecast fault.
3. Under explicit approval, qualify every permitted OFF/45/62/70 exact-prior
   transition, readback delay, native hysteresis/protection, owner intervention,
   OFF refusal and unconfirmed-command recovery. No blind POST repeats. Keep
   control off if any transition/state is uncertain.
4. Verify the command topic, advertised protocol, command-enable/auth/health,
   accounting, budgets and **Four-state commands qualified (1.3.14)** record.
   This historical label names the protocol’s introduction, not the installed
   bridge version. A verification switch never overrides the other guards.
5. Observe real fixed-poll request categories and app-change detection first.
   Only after independent approval qualify bridge adaptive scheduling and then
   enable both bridge flags plus controller plans. Compare actual intervals,
   missed changes, freshness, backoff and saved requests. Disable the flags to
   return to fixed mode. CT-free simulations did not show request savings.
6. Collect real clean target-specific sessions. Review ≥20 sessions/five days,
   whole-day held-out error/coverage, model/meter provenance and persistence.
   Set hardware qualification and learned planning only after independent review.
   Missing/changed/insufficient evidence must return to nominal planning.
7. Approve automatic-control activation separately, supervise normal storage,
   peak boundary and baseline return, and stop on unexpected behaviour. Activation
   and restart inspect a new status; they never replay a stored intent.

## Stop and troubleshoot

Turning automatic control off leaves the current appliance request in place.
Use the vendor’s approved manual operation for the installation when separately
authorised. The 12-hour Override is a real 70°C heating request when control is
active and can run at peak; cancelling it returns planning to ordinary guards.

| Symptom | What it means / next action |
|---|---|
| Missing qualification / advertised payload | Keep disabled; confirm reviewed versions and supervised evidence |
| Owner override/hold | An outside change is protected; inspect before explicitly resuming |
| Meter fault / stale zero | Optional heating is blocked; resolve raw unit/sign/report cadence |
| CT-free unknown element | Expected; cloud mode/nominal watts do not verify electrical draw |
| Forecast unavailable | When configured, notified outage; required heating uses conservative fallback |
| Peak lockout unverified | Software OFF is not confirmed; never claim zero electrical consumption |
| Auth lock / 429 / cloud backoff | Preserve lock/backoff and diagnose the cause, never retry by restart loop |
| Command unconfirmed/refused | Sent at most once or refused before POST; inspect app/state before recovery |
| Polling fixed_fallback | Missing/expired lease, disabled flag or scheduling persistence failure; fixed safety path applies |
| Learning nominal/insufficient | Normal fallback until real independent target-specific evidence qualifies |
| Setpoint higher than probe | Hysteresis/draws/loss/receipt delay; not proof of whole-tank or shower reserve |

Cloud OFF remains a software command, not a mains isolator. Native protection,
manual changes and outages remain possible. Confirmed cloud state alone never
proves zero electricity. [Rollback](UPGRADE.md) preserves guards and reconciles
62°C before restoring an older bridge.
