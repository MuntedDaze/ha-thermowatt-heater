# 1.3.7 read-only foundation — review candidate

Not merged or deployed by the agent. Review is required for new quota
classification and ordinary-cooldown persistence. Authentication and heater
control policies are retained; no live API call or Home Assistant access occurred.

## Configuration

```yaml
poll_interval_minutes: 30
poll_interval_unit: minutes
min_cloud_retry_minutes: 60
```

The Configuration tab labels the historic numeric key **Polling interval** and
adds a **Polling interval unit** dropdown. It is one numeric control, not two
competing interval values. With Seconds selected use 60–7200; with Minutes use
1–120. For 30 minutes expressed as seconds:

```yaml
poll_interval_minutes: 1800  # Historic key; value follows the selected unit.
poll_interval_unit: seconds
```

Old saved `poll_interval_minutes: 15` with no unit remains 15 minutes. Missing
both values remains 30 minutes. Unit/value cross-checks run before startup; a
combination outside 60–7200 seconds fails closed without cloud calls. Supervisor
validates individual field types/ranges; the native form cannot express the
combined unit-dependent range. Labels explain that constraint.

`min_cloud_retry_minutes` remains 60 by default (5–1440 allowed): it is the
minimum ordinary cloud-error cooldown, not an authentication reset or normal
polling interval. Existing exponential backoff remains at least both intervals.

## State, diagnostics and privacy

Credentials, tokens, existing guard records/generation, cloud/command flags,
native modes/schedule and all existing MQTT IDs remain. Linux private state and
options stay in the same `/data`. Do not uninstall/reinstall, replace all options,
delete private files or increase authentication generation to test this update.

New `/data/request_usage.json` stores six aggregate local lifetime attempt
categories, an accounting start timestamp, history-quality flags, local ordinary
cooldown and last fixed error code. It contains no account/device identifiers,
URLs, credentials, tokens or response bodies. Writes use the existing private
atomic writer (0600 on Linux). Counts are recorded before sending; interruption
can overcount an unsent attempt. They are **not confirmed server consumption**,
exclude the app/other clients and imply no vendor quota or reset time. Blocked
local requests do not count as sends. A new install begins a new local ledger.
Corrupt/unwritable storage reports incomplete/degraded accounting; it does not
unlock a guard or change command permission. Do not delete it to bypass a wait.

Healthy saved ordinary-error deadlines survive restart. Authentication retry
budgets/deadlines remain in their original separate guard; they are not replaced
with the ordinary cooldown. HTTP 429 still requires the original explicit
operator action. Exact JSON `error: Daily request limit exceeded` is labelled
`cloud_daily_limit`; unrelated failures retain generic diagnostics. No automatic
probe at a guessed vendor midnight/reset is introduced.

Five additional **read-only diagnostic sensors** share the existing device:
last successful poll, status age, cloud health, last known fixed error and local
lifetime request attempts. Diagnostic availability follows the bridge, so errors
remain visible when heater data is unavailable. Last poll/age start unknown on
restart until a new validated status; age updates locally without cloud calls.
The error sensor retains a fixed last-error code after recovery; health shows
the current state. Heating bitmask interpretation stays unverified/Unknown.

## Later controlled installation

Only after owner review/merge and separate installation approval, use the normal
Update action. Keep existing credentials/cloud flag/generation and commands
disabled. Select 30 Minutes / 60-minute error cooldown initially, especially
after vendor recovery. Verify existing entity IDs and the new diagnostics; do
not repeat login or restart cycles to gather evidence. Report fixed codes and
aggregate counts only. Actual Supervisor upgrade/UI behavior and live response
semantics remain unverified by offline tests.

See PHASE1_FORK_REVIEW.md for source decisions and PHASE2_CONTROL_DESIGN.md for
the design-only, separately approved HA/EMHASS work. Optional bounded demand
refresh is a separate follow-up and must stay disabled by default.
