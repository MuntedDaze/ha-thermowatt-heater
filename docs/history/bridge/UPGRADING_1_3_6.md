# Controlled 30-minute polling trial — 1.3.6

The owner approved this narrow polling/error-backoff change after the official
app reported a daily request limit. The numerical quota, its scope and reset
window remain unknown. This is a simple slower-polling trial, not a quota manager
or a guarantee that a particular daily allowance will not be exceeded.

## New option and timing

```yaml
poll_interval_minutes: 30
min_cloud_retry_minutes: 60
```

The polling option accepts whole minutes from 5 to 120, default 30. The minimum
cloud retry option accepts whole minutes from 5 to 1440, default 60. Older saved
options omitting either key use those defaults without rewriting the saved file. The first
eligible discovery/status cycle runs on startup. Normal cycles then wait at
least the configured interval from completion of the previous cycle. At the
default, ordinary failures start with a 60-minute delay, including
`cloud_success_false`, HTTP/server/transport errors, invalid JSON and malformed
device/status data. The base is the larger configured interval, doubling after
each consecutive failed cycle up to five exponent levels and a 24-hour ceiling.
Defaults yield 60, 120, 240, 480, 960 minutes, then stay at 960 on further failures.
Success resets the backoff. Retries never become more frequent than either
configured interval or fall into the old five-minute ordinary-error loop.

One heater nominally needs about 48 scheduled status reads/day at 30 minutes,
plus discovery, authentication/refresh, any enabled command/confirmation reads
and official-app activity. Multiple heaters increase requests per cycle.
Authentication GET 401 refresh/replay remains an existing bounded exception;
these settings are not a global HTTP-request cap. Polling deadlines, exponential
failure count and request counters are in memory:
restart permits another initial cycle, so repeated restarts defeat the intended
trial cadence. MQTT reconnection alone does not bypass an existing poll deadline.

## Usage accounting and daily-budget decision

Every cloud HTTP attempt is counted before sending, with only fixed category,
category count and total since startup logged. Categories are `password_login`,
`token_refresh`, `discovery`, `status` and `command`. All retries/replays count;
status includes command-confirmation reads, so confirmations are not omitted or
double-counted. A timeout/interruption may represent an uncertain server-side
request; these are attempted-request counts, not confirmed billable usage.
The official app and other clients are outside this counter. Startup explicitly
says counts reset on restart; they must not be mistaken for daily usage.

The safest minimal release defers a configurable persistent daily budget. We do
not know the vendor allowance, whether it is account/device/app-key scoped, or
whether it resets at midnight in any timezone or over a rolling window. A global
enforced cap could also block authentication/refresh or command-confirmation
requests and change protected policies. That enforcement needs separately
reviewed semantics/approval, not a guessed daily allowance. Persisting counters
alone would still not reveal app activity or the vendor's quota window. This
release therefore keeps observation and slow bounded polling without adding
new private files, migrations, reset assumptions or request-denial rules.

## Preserved state and behavior

- Same add-on identity, credentials, tokens, private guard format/paths, generation,
  lockouts, saved options, device identity and every MQTT entity ID.
- Installed cloud/command flags stay as configured. Do not replace installed
  options with the default/example configuration. New-install defaults remain
  false/false; the new polling/retry options default to 30/60 minutes.
- Authentication request/refresh logic, three-attempt transient budget, persisted
  60/300-second retry deadlines, five-minute successful-refresh cooldown and
  rejection/interruption/storage lockouts are unchanged. No generation reset,
  credential re-entry or token deletion is required for this version change.
- Existing command-loop cadence and command-confirmation reads remain separate
  from normal polling. No command is enabled or changed. The existing freshness
  guard still requires a recent confirmed status (60 seconds); at a 30-minute
  interval, most cached states are too old for commands. This guard is not relaxed.
  Commands remain disabled in the owner's trial. No heater/schedule/safety change.

1.3.6 is marked in `breaking_versions` for attention to slower data updates and
retry timing. This metadata does not change configuration or unlock the guard.

## Owner-controlled installation

1. Keep the add-on stopped while the vendor daily limit is active. Use normal
   vendor recovery guidance; do not assume a midnight reset or repeatedly log in.
   Leave the physical heater's own schedule, modes and safety controls alone.
2. Once you decide to install the trial, use the existing add-on's normal Update
   action to obtain 1.3.6. Do not uninstall/reinstall or delete private data. Retain
   your normal private backup; do not share its credentials/tokens.
3. Preserve existing email/password, `cloud_enabled` and authentication generation.
   Keep `commands_enabled=false`. Check `poll_interval_minutes: 30` and
   `min_cloud_retry_minutes: 60`; missing legacy keys also use those defaults.
4. When you approve resuming normal read-only operation after vendor recovery,
   start once. Verify `Poll interval=30 minutes.` and `commands=False` in startup
   logs, along with `Minimum cloud retry=60 minutes.`. Successful polling uses
   30 minutes; after an ordinary failure wait for the logged backoff (initially
   60 minutes), without restarting. The next consecutive failure waits 120 minutes.
   Request logs show per-run counts without sensitive response data.
5. Report only fixed operation/code pairs and whether read-only status/app access
   recovered. If the app daily-limit warning returns, stop the add-on for review.
   Do not reset authentication generation, enable commands or collect raw responses.

## Validation scope

Mocked-clock tests cover successful 30-minute polling, default/custom exponential
error delays/floors/caps, exact interval boundaries, discovery/status recovery, unchanged
authentication retries, MQTT reconnects, request counting (including refresh,
replay and confirmation), restart resets and command freshness/cadence. All prior
authentication/cooldown, envelope redaction, command-disablement and preserved-data
upgrade tests remain. Supervisor schema checks validate the new option; native
amd64/aarch64 containers check configured/default-fallback startup and existing
isolated MQTT lifecycle and private-data preservation. See the release PR's
final-head CI for results. No real Home Assistant update, authentication, cloud
API request or heater operation was performed by the agent.
