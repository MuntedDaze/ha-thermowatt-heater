# Bounded polling comparison (development only)

`adaptive_polling_shadow` defaults **false**. Enabling it records hypothetical
read times in controller telemetry. It never publishes MQTT, calls a service,
changes bridge options or authentication, or changes actual fixed polling.
One advisory scheduler runs in the existing serialized evaluation; no extra
timers or power-event cloud callbacks are introduced.

Caps default to 60 minutes while verified heating and 90 while stable. They
may be reduced within the visible System ranges (15–60 and 30–90). Missing or
uncertain observations propose an earlier check; imminent decisions/completion
can advance a check. Repeated sensor callbacks cannot push an existing due time
later. Command pre-reads and confirmations remain bridge-owned; successful
confirmation observations can be reused. Backoff/confirmation blockage is
reported and throttled, not bypassed. Local protective OFF still runs at the
ordinary control evaluation and never waits for this advisory temperature read.

`polling` in the telemetry event includes next due, reason, would-be status
reads, observed actual statuses, reused command reads, blocked evaluations and
`extra_cloud_requests: 0`. Counts restart with the HA integration; bridge's
durable request accounting stays authoritative. Shadow status counts are not
HTTP totals: token refresh, failed calls and command POSTs are separate costs.

The shadow comparison is conditioned on fixed-poll observations. Without an
independent timestamped owner-change or temperature-event ledger, missed events
and true detection delay on an alternative schedule are **unknown**. Offline
replays inject ground truth to measure these trade-offs. The earlier 107/59/50
figures in the audit are illustrative, not field observations or acceptance
targets. No vendor inactivity expiry has been established.

A future release enabling actual adaptive polling needs separate review of
bridge scheduling, expected status age across all consumers, guarded request
reserve, auth/session lifetime, owner-change detection and hardware traces.
This increment deliberately supplies the requested shadow stage only. Rollback:
turn off the comparison flag; actual fixed polling has never changed.
