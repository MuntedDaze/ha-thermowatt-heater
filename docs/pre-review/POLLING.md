# Focused polling evidence and limits

This phase changes observation scheduling, not command freshness, authentication
policy or the heater’s native protection. All new authority defaults off. No live
HA/vendor tests were performed. Independent review and separately approved owner
commissioning remain required.

## Why CT-free v1 used more requests

PR #35’s [frozen 8d2b1e4 results](https://github.com/MuntedDaze/ha-thermowatt-heater/blob/8d2b1e4a8c2c52818b73ddb082b7625c789b4425/docs/final-integration/WEEK_RESULTS.json)
recorded 730 versus 713 CT-free HTTP attempts. The ordinary 30-minute CT-free cap
could not save quiet-period reads. Advance observations ten minutes before a
planned command were then older than the bridge’s strict 60-second prior limit,
so the command needed another GET. Confirmation/pre-command reads shifted the
adaptive anchor and sometimes lost fixed-slot reuse. Existing 335 versus 334
refresh attempts show that there was no authentication saving to offset this.
With CT, the 40-minute cap saved ordinary reads and refreshes, but the same
advance-fetch/command duplication remained (27 versus 19 pre-command GETs).

The new scheduler removes the ten-minute prefetch: it observes at the real
pre-peak OFF decision (two-minute policy lead) or other consequential transition,
so that status can satisfy the unchanged strict prior where timing permits.
Otherwise the bridge still performs its own bounded fresh check. During required
temperature planning it rejoins half-hour observations instead of wandering onto
an arbitrary 40-minute phase. A first experiment with that arbitrary phase saved
requests but delayed scripted outage discovery and increased peak cost; it was
rejected. The regression comparison preserves cost/target outcomes explicitly.

## Four different freshness purposes

| Purpose | Guarantee / authority |
|---|---|
| Immediate command | Controller freshness gate remains configured poll interval + 5 min; bridge exact-prior status ≤60 sec or one permitted refresh; observed confirmation and all owner/auth/quota guards unchanged |
| Heating prediction/planning | Existing 45-minute temperature validity is unchanged; expired probes do not seed estimates. Active planning uses half-hour slots, with bounded spacing/confirmation reuse |
| Outside app-change detection | Explicit healthy quiet check maximum 30–90 min; 60 is the studied initial extended choice, not a promise during outages. Brief intervening changes can be missed |
| Passive dashboard | Last report/age remains visible; a temperature may intentionally become unavailable while a confirmed thermostat setting is held. A fresh-looking dashboard is not reason to manufacture measurements |

Quiet extension requires a confirmed steady baseline or Never-peak OFF, matching
observed setting, no pending command/owner hold and no failed mapped CT. A cold
reported baseline stays on progress observations. Forecast, tariff/boundary and
service deadlines remain local inputs. A qualified local solar opportunity can
make a fresh probe useful, but never directly calls HTTP or grants optional heat.

A new **Allow longer checks during quiet periods** controller permission defaults
false. **Maximum time between app-change checks** selects 30–90 min. The bridge
also requires its separate new **Longer quiet checks independently qualified**
option (default false on upgrades), plus its two existing adaptive flags. Existing
v1 qualification cannot silently grant v2 long intervals. Missing v2 capability or
qualification makes the requested new mode send no plans; the old fixed fallback
applies. V1 remains available explicitly for compatibility.

V2 plans identify purpose and owner bound. The bridge validates both against
hard 15–40 min active / ≤90 min quiet limits, exact successful-status anchoring,
finite typed values, newly issued timestamps and nonretained MQTT. Later hints
can advance but never slide a deadline later. Leases expire after 180 sec;
missing controller/journal failure/restart reverts to fixed recovery. Deadline
authority is monotonic. A validated passive lease suppresses only an inappropriate
passive age alert, never a stale command gate or stale temperature. Auth/backoff,
confirmation, quota and native protections retain precedence.

## Authentication investigation

The bridge already reuses one Requests session. Calling its worker/login check
every 20 sec is not a password login every 20 sec. Authorized idle ticks do not send
HTTP or refresh tokens. The existing 20-minute heuristic refreshes only before an
actual cloud operation; fewer ordinary reads therefore reduce refreshes too.
The quiet-tick regression proves no idle keepalive is introduced.

Prior field observations motivated that heuristic; they do not establish a
universal vendor access/refresh-token or inactivity lifetime. This phase changes
none of those constants, headers, credentials, cooldowns, persistence or retry
rules. GET 401 may refresh/replay once under the existing guard; POST is never
blindly repeated. Failed refresh after inactivity locks once without a following
status/command storm. Real inactivity/refresh behaviour at 60/90 min requires
separately authorised observation; do not assume the simulation qualifies it.

## Reproducible full-week comparison

Run `python tools/pre_review_replay.py --output docs/pre-review/WEEK_RESULTS.json`.
Tests reproduce every row and check HTTP categories, conserved energy, equal
demand/terminal energy, command counts, target success/shortfall and price outcomes.
The real controller/executor/bridge worker uses synthetic HTTP/MQTT/time/private
storage, denied external sockets and unchanged backoff logic. Eight weeks cover
CT/no-CT, sun/cloud/forecast errors, normal and heavy draws, both tariff boundaries,
night baseline, owner changes, CT/status outages, weekend and HA/history restart.
Focused tests add lease loss, quiet auth failure, v1/v2 qualification and actual
night app changes across 30/60/90 bounds.

This is a 315 L / 3 kW uniform tank with 8°C hysteresis and 0.2°C/hour loss, rounded cloud
probe and the owner-example tariff. Each run serves the same 45 kWh specified draw.
Equal-terminal cost includes hypothetical later off-peak replenishment, not an
executed cycle or a repaired missed target. Solar cost includes foregone export.
No stratification/native protective cycles or real vendor timing are modelled.

| CT | Strategy | Total HTTP | Status / refresh | Pre-command / POST / confirmation | Adjusted cost AUD | Persistent owner detection min |
|---|---|---:|---:|---:|---:|---:|
| no | fixed_30 | 713 | 327 / 335 | 10 / 20 / 20 | 7.0018 | 15 |
| no | fixed_60 | 380 | 160 / 169 | 12 / 19 / 19 | 7.4589 | 45 |
| no | event_aware_60 | 447 | 204 / 201 | 1 / 20 / 20 | 7.0018 | 45 |
| no | event_aware_90 | 365 | 163 / 160 | 1 / 20 / 20 | 7.0018 | 15 |
| yes | fixed_30 | 740 | 325 / 335 | 19 / 30 / 30 | 5.9299 | 15 |
| yes | fixed_60 | 408 | 159 / 172 | 20 / 28 / 28 | 6.3035 | 45 |
| yes | event_aware_60 | 493 | 211 / 209 | 12 / 30 / 30 | 5.9299 | 45 |
| yes | event_aware_90 | 420 | 176 / 174 | 9 / 30 / 30 | 5.9299 | 15 |

Each includes one synthetic login; discovery is zero because the fixture already
knows its synthetic device. Failed attempts count too. Savings versus fixed-30:
**37.3% CT-free / 33.4% measured at 60**, and 48.8% / 43.2% at 90. The90-minute example
happens to catch the chosen owner change sooner than 60 because of poll phase;
its worst permitted detection is longer, not better. Neither detects the
five-minute transient change. Night tests exercise changes just after a confirmed
read to verify the selected bound, without weakening exact-prior protection.

| CT | Strategy | Worst healthy / including outage age min | All temperature-unknown / required-planning unknown min | Stale-command blocked min |
|---|---|---:|---:|---:|
| no | fixed_30 | 29.7 / 89.0 | 44 / 12 | 32 |
| no | fixed_60 | 60.7 / 118.0 | 2362 / 393 | 0 |
| no | event_aware_60 | 59.7 / 89.0 | 2014 / 12 | 32 |
| no | event_aware_90 | 89.7 / 89.7 | 3889 / 12 | 32 |
| yes | fixed_30 | 31.7 / 67.7 | 23 / 0 | 32 |
| yes | fixed_60 | 61.7 / 96.7 | 2280 / 322 | 0 |
| yes | event_aware_60 | 59.7 / 74.7 | 1851 / 0 | 39 |
| yes | event_aware_90 | 89.7 / 89.7 | 3527 / 0 | 39 |

Extended quiet modes deliberately have more **passive** unknown temperatures.
They do not have more required-planning unknown minutes than fixed-30. Stale-command
blocks are visible (including outage minutes); they trigger a fresh observation,
not a bypass. Measured quiet modes have seven extra blocked minutes in this
scripted week, with no lost command, extra POST, cost or target penalty. Fixed60
has hundreds of critical unknown minutes and a refused/unposted intent despite
fewer HTTP calls; it is not the recommended way to cut requests.

All runs serve the specified energy, but CT-free still misses the patchy-Wednesday
62°C probe target, as fixed-30 did. A late Friday draw leaves a boundary storage
deficit and the cloud outage prevents confirmed OFF. Extended modes preserve the
fixed-30 deficits and nonzero modelled unverified-lockout peak energy, rather than
hiding them. These are not proofs of shower comfort or electrical isolation.
The JSON retains each day’s actual/max temperatures, shortfall, grid/solar kWh,
forecast error, conditional completion errors, alerts and recovery decisions.
CT-free wall-clock completion stays unknown. Nominal minutes are separately
labelled conditional; learned authority remains default off and requires real CT.

## Recommended rollout

Start the owner’s CT-free installation with fixed-30, control disabled for read-only
checks, then separately supervised four-state/automatic qualification. Record real
request categories and outcomes over equal periods. After independent approval,
try event-aware 60 only if up to 60 min healthy owner-change detection is acceptable
and real inactivity/authentication behaviour passes. 30 is the tighter selectable
bound; 90 is studied but not the initial recommendation. No synthetic rate justifies
changing auth lifetimes or accepting missed service silently.

Observe temperature readiness/comfort, actual peak OFF, flags/lease fallback,
request counts and cloud/app delays. Stop dynamic mode if reliability or savings
do not justify it; missing v2 permission uses fixed fallback and disabling all
adaptive flags restores ordinary fixed polling. Native protections, overrides
and software-versus-physical OFF limitations remain. See the
[owner guide](OWNER_INSTALLATION.md) and [review handoff](HANDOFF.md).


## Additional multi-day failures

`python tools/pre_review_failure_replay.py --output docs/pre-review/FAILURE_RESULTS.json`
reproduces six additional weeks: fixed-30/fixed-60/event-aware 60, with and without
CT. Tuesday 01:15–02:00 AEST drops only scheduling messages; ordinary command
messages are unaffected. The event-aware runs drop 45 plans, observe lease expiry,
and make a real fixed-recovery status read during that gap. No replacement HTTP
loop is added in HA.

On Sunday the first refresh at/after 02:00 AEST returns a synthetic 401. Every
strategy ends persistently blocked, with **zero HTTP after refresh rejection**
and only the initial password login. No authentication generation is increased
or lock reset. Failure times differ with observation phase. Counts below describe
unavailable cloud control, not extra optimisation savings.

| CT | Strategy | Total HTTP | Status / refresh attempts | Pre-command / POST / confirmation | Adjusted cost AUD | Worst age incl failure min |
|---|---|---:|---:|---:|---:|---:|
| no | fixed_30 | 624 | 282 / 291 | 10 / 20 / 20 | 7.0018 | 1350.0 |
| no | fixed_60 | 335 | 137 / 147 | 12 / 19 / 19 | 7.4589 | 1380.0 |
| no | event_aware_60 | 406 | 183 / 181 | 1 / 20 / 20 | 7.0018 | 1349.7 |
| yes | fixed_30 | 651 | 280 / 291 | 19 / 30 / 30 | 5.9299 | 1350.0 |
| yes | fixed_60 | 363 | 136 / 150 | 20 / 28 / 28 | 6.3035 | 1380.0 |
| yes | event_aware_60 | 452 | 190 / 189 | 12 / 30 / 30 | 5.9299 | 1322.7 |

The JSON reports all daily targets/deficits, energy, costs, counters and fault
annotations. The Sunday failure occurs while an existing baseline is selected,
with no later required weekday in this replay; it does not prove Monday control
would remain available. The heater’s simulated native thermostat continues,
but cloud state/confirmation cannot be trusted after the fault. Owner recovery
is deliberately left outstanding. Never count locked-out requests as savings
or infer real hot-water comfort from the uniform-tank demand model.
