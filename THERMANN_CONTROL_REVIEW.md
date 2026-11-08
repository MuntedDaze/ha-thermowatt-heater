# Thermann compatibility and control review — 2026-11-09

Scope: a small read-only presentation correction after the owner's successful
1.3.2 installation. No HA access, live cloud requests, authentication, heater
commands or schedule changes were performed for this review. The separate Windows
login workflow remains cancelled. Authentication safeguards and command handling
are unchanged; `commands_enabled` still defaults to false.

## Evidence and its limits

The owner reports the following for an Australian Thermann Smart Electric 315 L,
3 kW heater in Home Assistant OS:

| Observation | Status |
| --- | --- |
| Thermann Control authentication and MQTT discovery | Successful, owner-reported |
| Current temperature: app/heater display and HA both 17°C | Matching snapshot, owner-reported |
| Target temperature: app/heater display and HA both 70°C | Matching snapshot, owner-reported |
| Thermann mode Schedule; HA water-heater mode Unknown | Explained by HA's limited mode vocabulary |
| HA Heating: Normal | Previously derived from an unverified bit; not physical-element evidence |
| Configuration | `cloud_enabled=true`, `commands_enabled=false` |
| Thermann app / heater / Wi-Fi versions | 3.15.17 / 07.00.09.06 / 01.03.21 |
| App controls | Manual, Schedule, Eco, Holiday, plus separate power control |

Matching displayed temperatures establish agreement at that observation, not
independent probe calibration, uniform tank temperature or usable hot-water
capacity. No HA write has been tested. The reported Schedule state is consistent
with the existing `Cmd=17` Auto mapping; a real raw `Cmd`/`WaterHeaterSts` sample
was not supplied for this review. These numeric mappings remain inherited source
conventions, not a vendor-published protocol specification.

## Minimal MQTT correction

[HA MQTT water-heater modes](https://www.home-assistant.io/integrations/water_heater.mqtt/)
must come from its supported vocabulary. It has no Schedule or Holiday mode.
The existing water-heater topic, unique ID `thermowatt_<serial>_v314`, device ID,
temperature fields and native modes remain stable. Schedule/Holiday continue
to produce native Unknown rather than being mislabeled Manual, Eco or Off.

One read-only **Vendor mode** sensor is added on
`homeassistant/sensor/<serial>/vendor_mode/config`, unique ID
`thermowatt_<serial>_vendor_mode`, using the same device and availability topics.
It uses the existing `/status` poll; no additional cloud request or endpoint is
introduced. It has no command topic.

| Raw Cmd | Vendor-mode label | Native HA water-heater mode |
| --- | --- | --- |
| 9 | Manual | performance (existing mapping) |
| 3 | Eco | eco |
| 17 | Schedule (legacy Auto) | Unknown |
| 65 | Holiday | Unknown |
| 16 | Off (legacy power code) | off |
| Other nonnegative integer | Unknown, raw code retained | Unknown |

The app's separate power control means a mode label is not a complete power-state
model. In particular, code 16 does not reveal the mode remembered for power-on.
Unknown codes no longer discard otherwise valid temperature readings. Malformed
codes and malformed status still fail validation. `Cmd` and `WaterHeaterSts` are
exposed as mode-sensor attributes, with `heating_status_verified=false`.

### Physical heating state

The upstream bridge interprets `WaterHeaterSts & 1` as heating, but its comment is
not a bit-field definition or a measured validation. [Upstream issue #3](https://github.com/waterheater-dev/ha-thermowatt-heater/issues/3)
requests a heating indicator without establishing an encoding. No trustworthy
evidence reviewed here establishes that **any** value, including 0, 1, 2, 3 or
combined bit masks, proves the element energised or de-energised. Mode, demand,
temperature below target and a successful command are also insufficient.

HA's [heat binary-sensor device class](https://www.home-assistant.io/integrations/binary_sensor/)
labels its off state Normal. That UI label is not a Thermann diagnostic code.
The existing binary-sensor topic and ID `thermowatt_<serial>_heating` are retained,
but its name includes **unverified** and its template emits `None`, which
[HA treats as Unknown](https://github.com/home-assistant/core/blob/2026.11.0/homeassistant/components/mqtt/binary_sensor.py).
It deliberately ignores even old retained true/false values. The existing
`result.heating` field becomes JSON null; `result.vendor_mode` is additive.
Consumers must handle null as unknown, not cast it to false and assume no heating.
The raw status integer is retained without decoding it or inventing diagnostics.

## Existing commands: code review, not Thermann control verification

All rows below remain gated by the existing default-disabled command option,
fresh observed status and device/MQTT checks. Writes are never retried/replayed;
after a submitted write, the existing `/status` read compares observed values.
A match is cloud-state observation, not proof of physical heating or causation.

| Requested operation | Existing implementation | Limitation or side effect |
| --- | --- | --- |
| Manual | `MODE=Manual` → POST `/manual`, JSON `T_SetPoint` from last observed setpoint | Changes mode and sends a temperature together. Uses integer conversion, so a fractional observed setpoint would be truncated. No independent mode-only write is implemented. |
| Target temperature | `TEMP=<integer>` → POST `/manual`, JSON `T_SetPoint` | Only accepted when fresh Cmd is already 9. Schedule/Eco/Holiday temperature commands are rejected to prevent hidden mode changes. |
| Schedule/Auto | `MODE=Auto` → POST `/auto`, empty text/plain body; compare Cmd 17 | Existing legacy name is Auto. Native HA water-heater UI has no Schedule selection; the new sensor is read-only. Activating this route is not proof the stored weekly schedule is unchanged. |
| Eco | `MODE=Eco` → POST `/eco`, empty text/plain body; compare Cmd 3 | Device-managed behaviour may change temperatures and timing. Not suitable as a simple heating-demand switch. |
| Off | `MODE=off` or legacy `Off` → POST `/off`, empty text/plain body; compare Cmd 16 | No explicit separate On/resume command is implemented. Previous-mode restoration, anti-legionella behaviour and automatic fallback must be verified before use. |
| Holiday | Read Cmd 65; writes intentionally disabled | Old code invented a 30-day end date. No date/schedule write is added. |
| Explicit heating/boost request | Not implemented | Manual plus target is not an unconditional element-on command; do not bypass device protections or invent an endpoint. |

The current generic 20–75°C software bounds are legacy integration limits, not a
verified Thermann operating envelope. [Upstream issue #4](https://github.com/waterheater-dev/ha-thermowatt-heater/issues/4#issuecomment-3846191787)
also reports a 75°C request reverting to 65°C on another installation. This PR
does not change generic limits or any command API contract; Thermann-specific
limits must be settled before control approval.

## Manufacturer guidance and the fallback requirement

The [Thermann owner's guide](https://www.thermann.com.au/thermann-cms/files/Thermann-Smart_Electric-Owners_Guide.pdf)
describes Manual single-degree settings with a recommended minimum 50°C and
maximum 70°C, Eco managing its own setpoints/timing, and a stored daily Schedule.
It says app power-off retains antibacterial protection while mains power remains
available, but T-Comfort does not operate in Off/Holiday. The guide also describes
antibacterial-cycle notifications and temporarily blocking app setting changes
during that cycle. These are app/product descriptions, not proof that `/off`
preserves all protections or that firmware 07.00.09.06 has identical API behaviour.
Do not disable protections or retry commands against an active safety cycle.

A stored schedule is not an automatic fallback while the device is deliberately
left in Manual or Off. The current bridge sends no recovery/fallback commands
when HA, MQTT or the cloud fails. Retaining the saved program alone cannot
guarantee 7 am / ~4 pm comfort; device execution during each outage and safe
resumption must be established before automated control.

## Active schedule and diagnostics: what is actually understood

The local bridge and reviewed upstream source use GET `/status` and GET
`/user-info` for reads. Understood fields are `T_Avg`, `T_SetPoint`, `Cmd`,
`WaterHeaterSts`, and the `result.termostati` device list/name/serial. The new
sensor only exposes the already-understood numeric diagnostics.

No documented weekly-program, active-slot, next-heating-time, T-Comfort, error
bit-field or antibacterial-status response schema was found in that source.
Cmd 17 identifies a mode convention, not the active schedule's contents. Neither
the current setpoint nor temperature reconstructs the program. Do not try a GET
on a known write route, guess a `/schedule` route, copy arbitrary response bodies
into MQTT attributes or interpret user-supplied firmware versions as API fields.

[Upstream issue #7](https://github.com/waterheater-dev/ha-thermowatt-heater/issues/7)
mentions an unsuccessful statistics request, not an understood schedule or energy
schema. It does not justify implementing or probing that route. No endpoint was
added or called in this review. If a later owner-approved, redacted existing-read
sample or manufacturer documentation establishes those fields, review them before
extending the allowlist. No further reverse-engineering is proposed now.

## Later owner-approved verification sequence — not executed

1. Review this PR and any version/release decision. After separately approved
   installation, keep commands disabled and verify Vendor mode/unknown heating,
   raw code attributes, availability and temperature agreement over normal use.
   Record the existing app schedule, power state and comfort/protection settings
   privately so restoration can be checked without changing the program.
2. Correlate raw status with naturally occurring heating using an existing visible
   element indicator or safely installed power meter. App labels alone are not
   physical feedback. Do not add an energised-bit interpretation without evidence
   for this firmware and combined flag values.
3. Before enabling commands, confirm model-specific safe bounds, an app-based
   recovery procedure and whether any safety cycle is active. Each command needs
   separate approval and one deliberate request; no bulk test or automatic retry.
4. Assess Manual using an owner-approved existing safe setpoint, then a small safe
   target change while already Manual. Verify the app, subsequent status and
   device response; expect mode changes only when explicitly requested. Keep the
   app available for recovery, and do not use the unverified generic 75°C ceiling.
5. Assess Auto/Schedule restoration. Verify the app reports Schedule and every
   saved day/slot remains unchanged, then observe actual scheduled operation.
   Assess Eco separately only if desired, then restore and recheck Schedule.
6. Leave Off until last: establish API power/resume semantics and manufacturer
   protection guarantees first. Confirm recovery and fallback without assuming a
   subsequent Manual/Auto write is a verified power-on operation. Holiday and
   explicit boost remain unsupported, not experimental test targets.
7. With device Schedule restored, later test HA/MQTT/cloud loss and recovery under
   owner supervision. Only after reliable control, energy feedback and fallback
   are verified should EMHASS optimise surplus solar, forecasts, import/export and
   tariffs against usable-hot-water availability by 7 am and around 4 pm.

No deployment or live step above is authorised by this report. Authentication
and Windows diagnostics need no further work for the successful read-only setup.

## Offline validation

Mocked tests exercise all inherited/unknown modes, the reported 17°C/70°C case,
actual Jinja templates, unchanged IDs and availability, legacy retained heating
booleans, opaque status combinations, malformed responses and the existing
single-write/readback command contract. Existing authentication tests remain.
Container checks require the read-only discovery and unknown-heating definitions
on the isolated broker, in addition to their prior startup/shutdown and zero-HTTP
checks. CI results are attached to the review PR; no HA UI or heater is used.
