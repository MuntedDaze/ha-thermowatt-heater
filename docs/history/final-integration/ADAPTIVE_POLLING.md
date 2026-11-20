# Actual adaptive polling, disabled until reviewed and commissioned

There is one HTTP authority: the bridge worker. Authentication, the existing
20-minute refresh heuristic, persistent attempt ledger, cloud backoff and exact
command/confirmation guards are unchanged. No token inactivity lifetime is
assumed. The old shadow comparison remains separately selectable and never
causes a request.

New controller setting **Send adaptive cloud scheduling plans** defaults false.
Bridge options `adaptive_polling_enabled` and `adaptive_polling_qualified` both
default false. Enabling one alone cannot activate scheduling. A fixed bridge
interval below 15 minutes retains the fixed schedule; it cannot inherit an
adaptive interval beyond its tighter command-freshness assumptions.

When separately enabled/qualified, the controller publishes a nonretained QoS0
plan at most once a minute to `P/<actual device>/poll_plan`. The existing command
topic binding supplies that device. This is a recommendation, not a GET or a
command. There is no second HTTP loop or dashboard dependency.

```json
{"version":1,"status_at":1794866400,"issued_at":1794866460,"delay_seconds":2400,"reason":"stable"}
```

Epoch seconds are UTC; the example values are synthetic. Accepted reasons are
`stable`, `heating`, `ct_free`, `uncertain`, `before_decision`, `near_completion`
and `recovery`. Payloads are limited to 512 bytes and exactly these five fields.
The successful status timestamp must match the bridge's own current observation;
plans must be newly issued within 30 seconds, finite and strictly newer than the
last accepted plan. Retained, wrong-device, stale, future and malformed plans
cannot authorise a read or extend the deadline.

Deadlines use monotonic time, anchored to the successful status. Ordinary
adaptive intervals are **15–40 minutes**, with a shorter cap inside the existing
configured temperature freshness allowance (five minutes reserved for recovery).
Fresh qualified CT input supports the longer stable/heating bound. CT-free mode
caps at 30 minutes; missing temperature at 15. Upcoming tariff/decision and
conditional completion observations can advance that bound. These are practical
conservative limits, not claims of verified vendor session lifetime.

The first valid plan for a new observation may replace its fixed slot. Later
callbacks can only advance its deadline, never slide it later. Every successful
confirmation, pre-command or demand read resets the anchor and invalidates plans
based on the previous read. Confirmation keeps its own existing two follow-ups;
the controller does not publish competing plans while confirming.

Plans lease authority for 180 seconds. If the controller/MQTT disappears, the
bridge uses its configured fixed interval from the last real status; an already
overdue fallback is due immediately. Restart forgets leases, cached status and
monotonic deadlines and performs the normal startup inspection. The compact
`poll_state.json` stores diagnostic counters only. Corrupt/unwritable journal
state disables adaptive scheduling in favour of fixed polling; it cannot clear
authentication locks, cloud budgets, command state or previously unknown outcomes.

The bridge publishes actual mode/reason, next background timestamp, effective
interval, lease remaining and counters under its existing diagnostic channel.
The controller's actual next-poll/interval sensors use these diagnostics while
adaptive is enabled. Shadow next-poll/interval remain explicitly hypothetical.
Command-related reads can happen sooner. If the cloud is backed off/locked, a
desired poll is not a promise it can run; no plan shortens the backoff.

The legacy fixed mode remains clock-aligned when adaptive is disabled. The
enabled mode's fixed fallback is bounded from the last successful observation.
Ordinary status staleness and the bridge's 60-second exact-prior command check
are not relaxed. An unexpected local opportunity can wait for a fresh read;
forecast, nominal power and learned estimates cannot replace that evidence.

Real vendor behaviour and owner-change detection trade-offs need supervised
observation before activation. Synthetic comparisons and regressions validate
the implementation; they are not proof of real API savings or commissioning.
