# Manual plus native On/Off — evidence review, 10 November 2026

**Verdict: credible at the product/app level, not yet qualified for API execution.**
The manufacturer finding supports software Off as a potential normal-heating
gate while keeping native protection powered. The remaining missing contract is
programmatic resume, mode/target retention and this firmware's outage behaviour.
The accepted 0.2.0 planner is unchanged. No live request, command, HA access,
deployment, reset, programme edit or optimiser redesign was performed.

## Manufacturer evidence versus installation-specific evidence

The [official guide, printed p10/PDF p16](https://digitalassets.reecegroup.com.au/m/65539137e892f4b1/original/Installer-s-Manual-Thermann-Smart-Electric-Water-Heaters.pdf#page=16)
explicitly documents app Off with antibacterial control active while mains stays
connected, and resumption using the same app button. It also says saved settings
survive power cycling, and that antibacterial algorithms may differ between
models. Printed p9 describes approximately 8°C reheat hysteresis. These are
positive product-level evidence, not a verified mapping of `/off` or its inverse
on owner-reported firmware **07.00.09.06** (Wi-Fi 01.03.21, app 3.15.17).

The reviewed section does not specify Off→On Manual/target retention or normal
heat resumption after an outage. No owner factory-reset-to-65°C procedure was
established. Absence from this evidence is not proof no such procedure exists.

## Source-supported API findings

Local source baseline: commit `8b1a6bf`, `process_command`, `poll_status` and MQTT
discovery in `thermowatt-heater/thermowatt_bridge.py`. This review changes none of it.

| Finding | Established in source | Not established |
| --- | --- | --- |
| Off | MODE `off`/`Off` → POST `/off`, empty text/plain body; one `/status` read; compare Cmd 16 | Equivalence to the official app's power toggle; physical state or hygiene confirmation |
| Manual | POST `/manual` with last observed `T_SetPoint`; compare Cmd 9 | Whether this also clears native soft-Off or resumes the previous state |
| Target | `/manual`, allowed only when last observed mode is Manual | Power resume or hysteresis override |
| Auto/Eco | POST `/auto` or `/eco`; expect Cmd 17/3 | A reversible independent On command or last-mode restore |
| Separate On | No supported `On`, `on`, `resume` or POWER dispatch | An endpoint or payload must not be invented |
| Retention | Off sends no explicit target/memory field; subsequent reads publish observations | Same reported target does not prove a saved Manual target; Cmd 16 does not encode previous mode |

Notably, if Off reports a different target, the existing next MODE Manual command
uses that **newly observed target**, not a remembered pre-Off value. A future
executor must capture and explicitly reconcile approved intent rather than assume
retention. Source/mocked behaviour is not proof of what the heater actually returns.

Discovery has a mode command topic but **no power command topic**. HA Core's
[MQTT water-heater source](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/mqtt/water_heater.py#L262)
advertises independent On/Off only with a configured power topic. Generic HA
`water_heater.turn_on` is therefore not a hidden Thermann resume solution here.

The following public bridge snapshots were also inspected, without copying code,
keys or certificates. Their command handlers expose the same mode/Off pattern;
none supplies a separately supported On/resume operation. This is a bounded
source review, not a claim about every app build or unpublished vendor protocol.

| Repository | Reviewed commit and command handler |
| --- | --- |
| [waterheater-dev](https://github.com/waterheater-dev/ha-thermowatt-heater/blob/ef827e7385d7d56d3bd6f1c1cb5836013bea74f9/thermowatt-heater/thermowatt_bridge.py#L196) | `ef827e7` |
| [MMicieli](https://github.com/MMicieli/ha-thermowatt-heater/blob/464093362673ec95a9c9e561454bc7ffea3d9aca/thermowatt-heater/thermowatt_bridge.py#L2034) | `4640933` |
| [savvaskoualis](https://github.com/savvaskoualis/ha-thermowatt-heater/blob/546820f2f00d68edbc3ec020c3b60ba5af3ded5f/thermowatt-heater/thermowatt_bridge.py#L1034) | `546820f` |
| [echoztrip](https://github.com/echoztrip/ha-thermowatt-heater/blob/43b7ed3ce2a09956853ee8dd4059198856e1195b/thermowatt-heater/thermowatt_bridge.py#L349) | `43b7ed3` |

## Outage and recovery matrix while previously Off

These rows distinguish the documented product expectation from inference and
unqualified behaviour. Antibacterial availability is not daily comfort readiness,
and software Off is not electrical isolation or guaranteed zero consumption.

| Event | Evidence/expectation | Conservative controller treatment |
| --- | --- | --- |
| HA or MQTT stops; heater remains powered/networked | No new automation writes. Product-level hygiene expectation remains if native soft-Off was actually engaged; firmware behaviour has not been exercised. | Never assume saved Schedule wakes an Off heater. Alert/reconcile after recovery; owner may use the official app. |
| Internet/vendor cloud unavailable | Same native-state expectation, but remote app/bridge control may be unavailable together. | Do not claim an independent app recovery route during the outage. Normal heat may remain disabled; accept the owner's manual-recovery risk and obtain support if unavailable. |
| Mains failure | No electrical heating while unpowered; settings retention is documented. | Do not promise automatic ordinary-heating resume after power restoration or treat a possible hygiene cycle as such a resume. |
| Bridge/HA restarts | Saved auth state and normal discovery/polling persist under existing protections; the shadow controller sends no resume. | Observe actual power/mode/target before any separately approved future action. Never replay an interrupted write or reset an auth lock. |

**Owner recovery when the app works:** inspect the app's power state; if it is
Off, the documented recovery is the same app power button, followed by checking
mode and target. Then select/verify native Schedule if returning to the known
programme, or deliberately select approved conventional Manual settings when
appropriate. Power On must not be inferred just from choosing a mode. These app
steps are documented operator actions, not actions executed or physically verified
by this agent. Allow the native thermostat to decide whether the element runs.

If neither app nor cloud is available, no independently verified owner-local
resume/reset path was found. Contact Thermann for the model/firmware-specific
recovery instructions; technician help may be needed. Do not remove covers,
alter the thermostat, reset safety cut-outs or cycle mains hoping for a reset.

## Bounded-cycle proposal — design only

After resume/retention/protection qualification, **Manual at an approved 65–70°C
storage target + native soft power gating** could implement bounded morning and
daytime opportunities without making 40°C a storage setpoint. Keep T-Comfort
10°C and saved Schedule unchanged. Prefer handback when communications work;
universal automatic handback during outages is not required by the owner.

- Start with at most the two planned daily opportunities (morning only if needed,
  then daytime storage), not a command for each one-minute planner update. Any
  additional routine cycle requires a separately approved policy/budget.
- Keep the planner's ten-minute sustained-export gate. Proposed initial minimum
  active/park dwell is one background-poll period (30 minutes), subject to
  supervised qualification, never a justification to suppress manufacturer safety.
  Brief clouds can change cost estimates without producing repeated Off/On.
- A cycle has an immutable ID, captured mode/target/power evidence, finite intended
  end time and one outstanding command. Record intent before sending. Send one
  qualified resume and one qualified stop at most; any necessary setup/target
  write is separately counted. No retry after rejection, timeout or ambiguity.
- Normal telemetry stays at 30 minutes. Before each write, the bridge still needs
  observed state no older than 60 seconds and a command no older than 30 seconds.
  The accepted 45-minute shadow freshness limit is **not** execution permission.
  A new bounded pre-read path would need separate approval; on-demand stays off.
- Use the bridge's existing one post-write observation, with a finite wait for
  worker/HTTP completion. Never add unbounded confirmation polls. Proposed waits
  must account for GET→refresh→replay and cannot bypass the five-minute refresh
  guard, ordinary cooldowns, persistent auth locks or disabled commands.
- Illustrative request allowance per intent: pre-read 1 (or 3 with refresh/replay),
  one write, confirmation 1 (or 3). Reserving 7 slots is conservative accounting,
  **not permission** for both refreshes: the guard can stop the sequence earlier.
  A two-write cycle could need 14 slots; setup adds more. Include login/discovery,
  status, refresh, command and confirmation categories from the lifetime ledger.
  No vendor daily allowance/reset time or acceptable extra daily volume is known.
  Do not reset accounting or retry quota failures to complete a cycle.
- A finite intended cycle does **not** guarantee a finite physical heating window
  when stop communication fails. While On, Manual may maintain heat; while Off,
  normal heat may stay unavailable. Mark uncertain state, halt further automatic
  intents and alert the owner. Do not loop Off/Auto as recovery.
- Native hygiene may heat during a parked window. Do not treat that alone as a
  failed Off, repeatedly suppress it, or promise all peak import is eliminated.

## Hysteresis and supervision prerequisites

On means heating **permitted**, not forced. At a 70°C target and 65°C bottom
reading, heat may not start until roughly 62°C. Off/On resetting that latch has
not been established; it must not become a hysteresis-bypass strategy. Keep the
simple time model and its warning; never raise above approved limits to force heat.

Before any API-Off trial, separately approve a supervised **official-app**
Manual→Off→On observation with a known recovery route, recording selected mode,
target, power indication and native protection information. This is not executed
now. Seek vendor/source support for the corresponding resume operation before
testing that API operation. Do not first park the heater through an API whose
inverse is unavailable. Mode/target readback, actual element behaviour and hygiene
configuration are different confirmations. Firmware-specific manufacturer advice
is appropriate; deliberately forcing a hygiene cycle or outage is not required.

Outstanding questions for Thermann: supported resume mechanism; Manual/target
retention; Off behaviour across network/mains loss; applicability of the stated
antibacterial behaviour to firmware 07.00.09.06; and owner-local recovery when
the app cannot connect. No message has been sent on the owner's behalf.
