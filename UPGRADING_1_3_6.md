# Controlled 30-minute polling trial — 1.3.6

The owner approved this narrow polling/error-backoff change after the official
app reported a daily request limit. The numerical quota, its scope and reset
window remain unknown. This is a simple slower-polling trial, not a quota manager
or a guarantee that a particular daily allowance will not be exceeded.

## New option and timing

```yaml
poll_interval_minutes: 30
```

The option accepts whole minutes from 1 to 1440. The default is 30; older saved
options omitting it also use 30 without rewriting the saved file. The first
eligible discovery/status cycle runs on startup. Normal cycles then wait at
least the configured interval from completion of the previous cycle. At the
default, an ordinary cloud polling failure also waits at least 30 minutes before
another cycle, including `cloud_success_false`, HTTP/server/transport errors,
invalid JSON and malformed device/status data. It cannot fall into the old
five-minute ordinary-error retry loop.

One heater nominally needs about 48 scheduled status reads/day at 30 minutes,
plus discovery, authentication/refresh, any enabled command/confirmation reads
and official-app activity. Multiple heaters increase requests per cycle.
Authentication GET 401 refresh/replay remains an existing bounded exception;
this setting is not a global HTTP-request cap. Polling deadlines are in memory:
restart permits another initial cycle, so repeated restarts defeat the intended
trial cadence. MQTT reconnection alone does not bypass an existing poll deadline.

## Preserved state and behavior

- Same add-on identity, credentials, tokens, private guard format/paths, generation,
  lockouts, saved options, device identity and every MQTT entity ID.
- Installed cloud/command flags stay as configured. Do not replace installed
  options with the default/example configuration. New-install defaults remain
  false/false; the new polling option defaults to 30 minutes.
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
   Keep `commands_enabled=false`. Check that `poll_interval_minutes` is 30; if an
   older options file omits it, the bridge still defaults to 30.
4. When you approve resuming normal read-only operation after vendor recovery,
   start once. Verify `Poll interval=30 minutes.` and `commands=False` in startup
   logs. Allow at least two full intervals without restarting. Identical warnings
   may log only once; absence of repeat messages is not proof that no retry occurs.
5. Report only fixed operation/code pairs and whether read-only status/app access
   recovered. If the app daily-limit warning returns, stop the add-on for review.
   Do not reset authentication generation, enable commands or collect raw responses.

## Validation scope

Mocked-clock tests cover successful and repeatedly failed 30-minute polls, the
exact interval boundary, custom intervals, discovery/status recovery, unchanged
authentication retries, MQTT reconnects and command freshness/cadence. All prior
authentication/cooldown, envelope redaction, command-disablement and preserved-data
upgrade tests remain. Supervisor schema checks validate the new option; native
amd64/aarch64 containers check configured/default-fallback startup and existing
isolated MQTT lifecycle and private-data preservation. See the release PR's
final-head CI for results. No real Home Assistant update, authentication, cloud
API request or heater operation was performed by the agent.
