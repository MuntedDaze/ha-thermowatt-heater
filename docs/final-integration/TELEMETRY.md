# Combined engineering interface

Bridge 1.3.15 / controller 0.11.0 on draft PR #35. This extends, rather than
replaces, the [schema-2 four-state contract](../dual-storage/TELEMETRY_INTERFACE.md)
and [original smart-controller contract](../smart-controller/TELEMETRY_INTERFACE.md).
Those documents describe their older candidate checkpoints; the deltas below
are authoritative for this branch. The combined [monitoring contract](../../energy_monitoring/ENTITY_CONTRACT.md)
is updated locally; Fable’s original #32 branch/worktree is unchanged.

## Ownership and data flow

`thermowatt_bridge.py` owns the only HTTP session, auth/guard/usage/command stores,
background timer, pre-command exact-prior read and confirmation sequence. Pure
`model.py`/`simple_policy.py` choose a desired state, `controller.py` gates it,
and `executor.py` persists/publishes an intent. The runtime only reads local HA
states. Dashboard/forecast/history code cannot call vendor HTTP. MQTT plans can
adjust the bridge’s existing timer only after validation; they are not commands.

`measurement.py` accepts raw signed exclusive-circuit W/kW and optional native
Wh/kWh. It never accepts the dashboard’s absolute or integrated wrappers as
control authority. Commissioning identity, boot/receipt/freshness/unit/polarity
and paired-grid timing remain required for optional solar. A mapped meter fault
is distinct from a deliberately CT-free installation. AC/oven/dashboard absence
cannot alter hot-water qualification. Do not duplicate native and integrated
energy, recover missing timing from cumulative deltas or invent zero watts.

## Additive entities and events

Existing domain, stable unique-ID suffixes and MQTT topics remain unchanged.
Resolve actual registry IDs if users renamed entities. New suffixes below use
`<config_entry_id>_<suffix>`; suggested names in the entity map are generated from
stable display names. All are read-only sensors, separate from enable settings.

| Stable suffix | Meaning |
|---|---|
| `baseline_target_c` | Selected baseline target, not achieved temperature |
| `adaptive_polling_status` | Actual bridge mode/reason, including fixed fallback |
| `next_cloud_poll`, `cloud_poll_interval` | Actual bridge next scheduled poll / seconds; confirmation/backoff can govern earlier/later work |
| `next_adaptive_poll`, `adaptive_poll_interval` | Retained hypothetical shadow comparison only |
| `learning_status` | Planning basis/fallback reason |
| `learning_sessions` | Eligible clean target/model/meter cohort count |
| `prediction_error` | Held-out heating-time MAE minutes, unknown without samples |
| `planning_heating_rate` | Nominal fallback or eligible conservative learned rate for the normal target, before any additional slower live-watt cap |
| `learned_heating_rate`, `prediction_confidence` | Retained diagnostic calibration/completion status; not permission for learned planning |
| `tariff_verification` | Explicit verified/unverified contract choice |
| `feed_in_rate_aud` | Configured constant feed-in rate; not a time-varying price model |
| `current_price_aud` | Current quote from the one controller tariff schedule |

The schema-2 `controller_telemetry` event retains all old objects and adds
`learning` with eligibility, sample/day/training/held-out counts, rates/variation,
error/coverage, chosen basis and `affects_control`. `heating_plan` includes
`planning_rate_c_per_hour` / `planning_rate_basis` when calculated. Calibration
remains a distinct diagnostic object. The existing event `polling` object remains
the shadow comparison; actual bridge `DIAGNOSTICS` attributes carry the new
`adaptive_polling`, `polling_mode`, `polling_reason` and `next_scheduled_poll`.
Consumers must accept unknown/null/missing fields and future reason codes.
Events are meaningful changes, not a raw sample stream; Recorder keeps originals.

The dashboard now maps four-state roles, predicted completion, actual and shadow
polls, learning, budget, peak policy and CT availability. Combined prices read
verified controller quote entities by default. Standalone monitoring-only
peak/off-peak helpers remain optional and never control heating.

## Adaptive scheduling wire contract

Both bridge options `adaptive_polling_enabled` / `adaptive_polling_qualified`
and controller `adaptive_polling_enabled` default false. The actual bridge needs
a configured fixed interval ≥900 seconds. Every minute at most, the controller
may publish nonretained QoS0 `P/<serial>/poll_plan` containing exactly:

```json
{"version":1,"status_at":1794762000,"issued_at":1794762060,"delay_seconds":1800,"reason":"ct_free"}
```

Times are UTC epoch seconds. The plan must match the bridge’s own last successful
status (0.01 second tolerance), be newly issued within 30 seconds, finite and
≤512 bytes. Retained, duplicate, stale, future, wrong-device, extra/missing-key
or non-enumerated reasons are rejected. Permitted reasons are `stable`, `heating`,
`ct_free`, `uncertain`, `before_decision`, `near_completion`, `recovery`.

The bridge anchors deadlines to monotonic time at the actual successful read.
A first lease may replace its fixed slot; later hints can advance but never
slide the pending deadline later. The lease expires after 180 seconds. Hints
are bounded 900–2400 seconds; the controller caps CT-free at1800 and leaves five
minutes inside configured temperature freshness. Consequential decision/completion
reads can be earlier within those limits. Already-selected normal storage does
not spend GETs on a hypothetical new start. Confirmation/pre-command reads reset
the anchor; an old hint is then invalid. Callbacks only queue, never execute HTTP.

Missing/expired lease returns to fixed duration from the last actual read. Auth,
HTTP429, guard failure, error backoff, quotas, owner holds, exact-prior command
validation and confirmation retain priority. Restart discards leases/cached
status and re-inspects; journal stores diagnostic counts only. Corrupt/unwritable
journal selects fixed fallback. New flags or journal data never authorise a login
or POST. Actual ordinary/reused reads and reasons remain diagnostic counters.

## Learning, history and planning

[Learning](LEARNING.md) defines complete-start/session provenance, target/model/
meter cohorts, robust fit, whole-day holdout, error bounds and explicit gates.
The existing compact v2 sidecar retains optional new fields; old rows are never
relabeled qualified. No second raw database is added. A usable learned rate must
be at most nominal/live-watt physics: it can bring a required start forward,
never optimistically delay it. Real data/hardware qualification are outstanding.

One tariff model in `model.py` drives current prices, future slot economics,
peak guards and deadlines. `installation.py` distinguishes legacy compatibility
from actual fresh HA-zone/flat/unverified defaults. [Tariffs](TARIFFS.md) specifies
month/day/window semantics and unsupported advanced billing; it is not a second
planner or a retail contract validator.
