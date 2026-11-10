# Thermann control and recovery — source/public-document review only

No live API, authentication, command, reset or hardware test was performed.
This updates the earlier Phase 2A design: the owner accepts occasional manual
recovery during serious outages. Automatic Schedule restoration in every failure
is **not** a required architecture guarantee. Thermostat, over-temperature and
manufacturer hygiene protections remain mandatory; read-only Phase 2A remains.

## What the existing v1.3.8 bridge implements

These are inherited community API contracts, verified in source and mocks only,
not a published vendor API or physically qualified commands for this heater.
The shadow planner neither imports nor invokes them.

| Operation | Existing route and behaviour | Execution implication |
| --- | --- | --- |
| Status/discovery | GET `/status`, GET `/user-info` | Current fields do not expose a verified element-on bit, native clock, saved weekly programme or T-Comfort schema. |
| Manual | POST `/manual` with `T_SetPoint`; MODE Manual uses the last reported target | Changes mode and target together. A 65–70°C Manual setting can keep reheating indefinitely; it is not a bounded heating pulse. |
| Setpoint | Same `/manual` route; TEMP accepted only when already Manual | No 40°C storage command is proposed. Legacy bridge 20–75°C validation is not model-specific approval. |
| Auto/Schedule | POST `/auto`; empty text body; expect Cmd 17 | Desired handback when communications work. Mode readback alone does not prove programme retention, power resume or physical heating. |
| Eco | POST `/eco`; expect Cmd 3 | Adaptive native behaviour, not an optimisation on/off switch. |
| Off | POST `/off`; expect Cmd 16 | A known source route, but API-specific power, resume and protection behaviour remain unqualified. No automatic Off is proposed. |
| Separate On/resume or unconditional boost | Not implemented/verified | Do not invent endpoints or reinterpret Auto as a verified power-on command. |
| Holiday/programme/T-Comfort writes | Intentionally unsupported | No dates invented and no programme/comfort-setting edits. |

Writes are not retried. A following read compares observed state; submission or
HTTP success is not physical success. Existing guards, 60-second command-state
freshness, account lockouts and cloud budgets remain in the bridge. The planner
adds no new reads, writes or proactive token refresh.

## Can Manual achieve the proposed optimisation?

It can be a candidate way to request thermostatic heating at an approved storage
target, subject to qualification. The missing piece is a **verified stop/park**
behaviour. Leaving Manual at 70°C is continuous maintenance, not solar-only heat.
Handing back to Schedule can still heat inside the existing 04–08 / 11–17 or
06–22 windows. It cannot reliably stop at the morning 40°C decision threshold
while the current programme permits heating. T-Comfort 10°C is not the optimiser.

Consequently, the complete intelligent start/stop policy is not yet executable
with verified existing capabilities. Qualify the existing power/resume contract
or an explicitly approved alternative before adding execution. Do not substitute
unsafe low storage targets or repeated mode changes to work around that gap.
No substantial reverse-engineering is justified before this focused qualification.

## Manufacturer evidence and recovery limits

The [newer manufacturer guide](https://digitalassets.reecegroup.com.au/m/65539137e892f4b1/original/Installer-s-Manual-Thermann-Smart-Electric-Water-Heaters.pdf)
(printed pp9–11, PDF pp14–16) describes default Manual at 65°C, adjustable up to
70°C, approximately 8°C reheat hysteresis, and saved settings surviving mains
power cycling. Its pairing reset is not a factory reset. **No owner-accessible
factory-reset-to-65°C procedure was established in the reviewed documentation.**
The guidance does not qualify the raw API as a reversible power switch.

If the app and communications work, the candidate owner recovery is to select
native Schedule, verify the saved programme/target, and observe subsequent
operation. Conventional Manual around 65°C is another documented mode, but it
is not automatically recovered by a power cycle. Neither procedure has been
physically tested in this development task. If communications fail completely,
there is no verified remote or owner factory-reset recovery path to promise.
Ask Thermann support for model/firmware-specific instructions; manufacturer or
qualified technician help **may be needed**. Do not remove covers, change the
mechanical thermostat, reset a safety cut-out or modify electrical protections.

The guide's product-level descriptions of protections are not evidence that
`/off` retains every protection on this firmware. No Off/resume test or automatic
Off behaviour is authorised. Preserve the current native Schedule, 70°C target,
10°C T-Comfort and all manufacturer protections during shadow operation.

## Future execution architecture — separately approved work

1. **Measurements:** existing HA temperature/mode/grid/poll diagnostics. Keep the
   bridge as sole cloud client. Use bottom temperature directly, with plausible
   units/ranges; no additional physical sensor or stratification model is required.
2. **Planning:** this pure local model emits a goal, opportunity and latest
   off-peak backstop. 40°C is readiness logic, never a storage target. Recompute
   from new temperature observations and do not indefinitely wait for forecasts.
3. **Execution:** a later small adapter checks enabled permissions, ownership,
   fresh observed state and cloud status, then sends one verified intent via the
   bridge. Persist intent before submission; no automatic repeat on timeout,
   uncertainty, restart or a duplicate plan. Do not connect dashboard sensors
   directly to heater-command topics.
4. **Confirmation:** bounded, budgeted observation. Count any read, refresh,
   replay and confirmation. No physical-success claim from a successful POST,
   mode label or unverified Heating sensor. Hysteresis can prevent a requested
   70°C target from starting heat when already above roughly 62°C; never defeat
   it by requesting an unapproved higher target.
5. **Stable operation:** qualify minimum on/off dwell and a stop/park route first.
   Current grid export already includes any heater demand; do not stop/start
   repeatedly because energising a 3 kW element reduces export by about 3 kW.
   Reconcile observed manual changes as authoritative. Do not assume the unknown
   Heating sensor means off. Reliable supervised temperature trends can improve
   the time margin later, without inventing a power measurement or auto-fitting
   stratification from sparse mixed-use data.
6. **Failure:** stop new intents, retain the uncertain/last-confirmed state, expose
   a conspicuous fault and owner recovery instructions. Future owner notifications
   need an approved local notification route. When communication is available,
   try only a separately verified bounded Schedule handback. During a total
   outage, manual recovery is an accepted owner risk, not an automatic guarantee.
   Never loop Off/Auto or reset account locks to force recovery.

EMHASS can later supply price/forecast proposals through the same boundary. It
does not replace command qualification, manufacturer protections or human recovery.
See SUPERVISED_VALIDATION.md for the finite qualification sequence.
