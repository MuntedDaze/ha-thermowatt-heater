# Existing Thermowatt installation: controller 0.15.0 upgrade

Jacob already has **bridge 1.3.17** and **controller 0.14.0** installed. The owner
reports working bridge communication, Shadow Mode evaluation, GoodWe/HK1000
measurements and EMHASS. Development has not inspected or changed that live
installation. Older candidate/install notes describe historical development.

## What needs updating

| Component | Installed baseline | This upgrade | Owner action |
|---|---|---|---|
| Thermann Hot Water |1.3.17|1.3.17, source unchanged|No add-on update needed |
| Thermann Controller |0.14.0|0.15.0|Replace component source in its existing directory, restart HA once |
| Existing seven-view dashboard |Existing owner copy|Small hot-water status additions|Optional merge of new read-only rows; preserve custom mappings/views |
| GoodWe/HK1000 and MQTT |Working existing integrations|Unchanged|Keep existing entities, sign verification and broker |
| EMHASS |Already running|Existing forecast adapter, safer missing-load handling|Keep optimisation automation and generation timestamps |
| HA compatibility matrix |Existing environment|CI targets2026.10.4 and2026.11.1|Use the final PR's actual successful results; no speculative HA upgrade |

The source-review/tested commit, final CI and squash merge are recorded in the
completion PR and final owner report. Do not infer a merge from a version string
in a development archive. Use the exact reviewed main commit after merge.

## Normal in-place update

1. Confirm **Automatic heater control remains OFF/Shadow Mode** and bridge
   commands remain disabled. Record versions/options privately. Keep the working
   read-only cloud configuration, credentials and authentication generation as
   they are. Do not reset a lock, token, request counter or pending transaction.
2. Take and download a normal HA backup including configuration and the installed
   Thermann add-on's private data. Retain its recovery key. A verified isolated
   restore is stronger evidence than a backup file merely existing.
3. Download source from the exact reviewed main commit, or use its checked source
   bundle. Copy the complete contents of `custom_components/thermann_shadow/`
   into the **same** `/config/custom_components/thermann_shadow/` directory,
   overwriting source files. Keep that directory name and domain. Do not delete
   the config entry, re-add the integration, change MQTT discovery or edit
   `.storage`. Do not copy private runtime data from another installation.
4. Restart **Home Assistant once**, then verify controller 0.15.0, the original
   config entry, entity IDs/history, source mappings, targets, tariffs, holiday/
   override settings, command address and Shadow Mode. The bridge should still
   be1.3.17 and communicating through the same installed add-on identity.
5. Keep adaptive and learned authority at their existing qualified settings;
   this update enables neither. The new **CT-free solar commissioning record**
   defaults blank. It is not filled by migration, Restore defaults or development.
6. To use new dashboard rows, preserve the owner's `entity_map.yaml` mappings and
   add only the new hot-water keys from the example. Regenerate locally with
   `python energy_monitoring/build.py --map YOUR_MAP --out YOUR_OUTPUT`, then
   update the existing dashboard's hot-water cards. No new dashboard, duplicate
   sensor set or whole-home redesign is required. Controller operation does not
   depend on installing the monitoring package.

There is **no bridge update** in this release. When an actual future bridge
version is released, use Update on the **existing** Thermann Hot Water add-on
from its currently registered repository. Never add a branch repository or
duplicate add-on, manipulate Supervisor caches, uninstall or clear private data.

## Recommended operating choices and preserved settings

The agreed roles remain baseline45C, required weekday62C, optional economical70C.
Weekends use baseline plus eligible optional heat. The configured **Never schedule
heating during peak** choice continues to dominate solar until the owner elects
and qualifies **Verified solar-only heating**. A forecast does not authorise grid
import during peak. Morning45C by06:00 and42C by07:00 remain availability goals;
probe-based risk reporting does not guarantee them or issue an extra command.

Shared solar rules:3.3 kW raw export for a nominal3 kW element plus300 W headroom,
10-minute qualification,10 **continuous** minutes above200 W import before
withdrawal,15-minute normal command spacing and15-minute optional-start cooldown
after confirmed withdrawal. Genuine acceptable import resets withdrawal. Local
data expiry is bounded by the saved grid freshness setting (existing example120s).
Both start qualification and import withdrawal require continuous genuine
report coverage; an interrupting condition resets the corresponding window. Qualification may overlap cooldown.
Protective peak OFF can bypass ordinary spacing but never the bridge's command,
authentication, exact-prior, confirmation, persistence, quota or retry safeguards.

The10-minute delay precedes command delivery/confirmation. It is not a promised
physical cutoff. Unresolved-exit diagnostics show elapsed time and a nominal
3 kW exposure estimate. A CT reports power; it does not provide local disconnection.

## Owner-controlled commissioning

Continue the already working read-only installation first. The following are
future supervised checks, **not actions performed by this development cycle**:

- Verify the actual grid entity, signed W/kW units, direction with a known load,
  genuinely fresh reports including steady values, and unavailable/stale behavior.
- Confirm the original bridge/controller's supported OFF/45/62/70 transitions,
  exact-prior refusal, owner-app intervention, restart, delayed confirmation and
  unresolved-command recovery under separate command authorisation.
- Qualify CT-free solar only after those checks: enter the exact record
  `GRID_ENTITY|UNIT|DIRECTION|NOMINAL_KW`, for example
  `sensor.goodwe_inverter_meter_active_power|W|export_positive|3`. Use the actual
  saved mapping/unit/sign/rating. A mismatch blocks optional activity. A configured
  failed CT cannot downgrade to CT-free operation.
- Observe10-minute start qualification, consumed surplus without continued3.3 kW
  export, passing cloud versus sustained import, meter failure while START/OFF
  is pending, confirmed withdrawal/cooldown and essential off-peak recovery.
- Test the configured phone notification, protective-exit warning, controller
  evaluation watchdog and manual recovery. Authentication/unknown-outcome faults
  require owner inspection and acknowledgement; they are not automatically reset.
- Keep fixed 30-minute bridge polling initially. Longer event-aware quiet checks
  need their existing separate qualifications and real vendor/session evidence.
  Learned authority needs verified CT sessions and held-out accuracy; neither is
  activated by an update. GoodWe evaluations spend no cloud request per reading.
- Before unattended use, accept actual comfort/target outcomes, native behavior,
  verified tariff clock/DST, command latency, outage behavior and measured import
  exposure. Existing technical decision records remain authoritative.

Later CT: have a qualified installer identify an **exclusive heater circuit**;
map its raw signed active W/kW (optional cumulative Wh/kWh), verify ON/OFF,
steady-zero cadence, units, sign, timestamp and failure behavior, and save the
existing circuit commissioning record. The controller then uses metered watts;
missing data stays unknown. AC/oven/Tapo monitoring remains optional and separate.

## Recovery and rollback

For an unresolved protective OFF, check the explicit controller gate/fault and
the official Thermann app. Do not assume software OFF or a reboot proves zero
power. If remote control is unavailable, follow the manufacturer's local-control
instructions/qualified support. Never bypass electrical protections. Keep Hold
or automatic control OFF until the owner has reconciled the actual state; use
the existing Resume/Acknowledge controls only after checking the cause.

For a code rollback, keep control OFF, restore the backed-up0.14.0 component
source into the same directory, and restart HA. The config-entry schema/domain,
storage names, command protocol and old setting/entity IDs are unchanged. New
JSON state fields are additive and old code ignores them. **Do not downgrade
while a command/protective exit is unresolved:** old code does not understand
the new exit latch. Reconcile it first, or restore a coherent HA/add-on backup
under owner supervision with no second online bridge.
