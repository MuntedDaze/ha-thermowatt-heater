# 1.3.8 optional demand reads — dependent review candidate

Review the 1.3.7 foundation first. This is a separate stacked PR, not a second
independent replacement integration. Both remain unmerged and uninstalled by the
agent. Phase 2 control remains design-only and requires separate approval.

## Recommended initial configuration

Preserve existing credentials, cloud flag and authentication generation. Keep
commands disabled. Do not overwrite all options with a sample:

```yaml
poll_interval_minutes: 30
poll_interval_unit: minutes
min_cloud_retry_minutes: 60
on_demand_refresh_enabled: false
commands_enabled: false
```

Missing old unit/demand options mean Minutes/false. Existing 1.3.6 numeric values
remain minutes. Native modes/schedule, token/guard state, other settings and
existing entity IDs are retained. New diagnostic entities are the five from
1.3.7, not another replacement device. This candidate adds an attention marker
because the optional interface and retry scheduling require owner review.

## Optional read-only demand contract

Only after source review and a separately approved installation may the owner
enable `on_demand_refresh_enabled`. It does not depend on command enablement.
The protocol is a **non-retained** MQTT publication to `P/<serial>/refresh`,
payload exactly `refresh`; no actual device identifier is provided here.

- Only a currently discovered known device is eligible. Retained messages
  (including live retained writes/replays), unknown topics/devices, malformed
  payloads, disabled cloud, disconnection or a locked/not-authorised guard are
  ignored. Incomplete usage history also disables optional demand for review.
- The existing single worker performs reads; the MQTT callback only adds a
  device to a bounded set. Bursts coalesce to one device request. No new thread,
  cloud service, endpoint, transport retry or heater-command route is added.
- Demand is allowed only at least **300 seconds after the start of any status
  attempt** for that device, including normal polls and confirmation reads.
  Requests inside that window are dropped, not queued for later. Worker cadence
  can add up to about 20 seconds before processing, plus existing HTTP timeouts
  and any other device work. This is not a guaranteed freshness SLA.
- Authentication and error cooldowns always win. Requests during a cooldown or
  unverified recovery are discarded; only the normal worker can make a scheduled
  recovery attempt. Healthy persisted ordinary cooldowns survive restart.
  HTTP 429 retains the existing permanent operator lockout. No refresh resets
  generation, clears a lockout or deliberately initiates password fallback.
- A successful demand read moves that device's background deadline to avoid a
  redundant scheduled read. Other devices retain their own deadlines. Normal
  background polls follow the configured interval; explicit command-confirmation
  reads retain their existing behavior and are counted separately.
- The existing GET 401 → refresh → one GET replay remains. A demand cycle can
  therefore cost multiple HTTP attempts. Five-minute spacing is a local bound,
  not evidence of a sustainable vendor quota. No proactive JWT refresh is added.

Enabling demand can increase traffic: a continuously requesting caller could
cause about 288 read cycles per device per day at five-minute spacing, compared
with about 48 at the default 30-minute background interval. These are illustrative
cycle counts, not a request budget: authentication, GET replays, discovery and
other clients add requests, and configured background polling can be faster.
Leave demand disabled initially. Quota during login/refresh still locks the
authentication guard permanently pending operator action, including HTTP-200
daily-limit errors; waiting for vendor recovery does not unlock it. See the
operation-specific recovery distinction in UPGRADING_1_3_7.md.

## Smart polling evaluation

This supports a slow background (initially 30 minutes) with sparse demand reads
when an HA decision genuinely needs freshness. It deliberately does **not** add
an automatic mode driven by PV/grid/tariff state changes or dashboard listeners.
No HA/EMHASS caller is deployed. A future caller must:

1. Prefer already-fresh validated data; if necessary request one eligible read
   at a scheduled decision boundary, not on every optimiser or solar update.
2. Wait a finite time for a last-success timestamp newer than the captured one,
   cloud health `ok`, acceptable age and no failed cycle. A publication is not
   an acknowledgement that a read happened or succeeded.
3. Treat ignored, failed, timed-out or cooldown-blocked requests as unavailable
   data. Do not repeat requests rapidly or relax freshness gates to force action.

Five-minute caller decisions have little timing margin against five-minute
minimum spacing; jitter or another poll can make a request ineligible. Design
must accommodate that fail-closed case, not assume every decision gets new data.
The existing 60-second command-state freshness guard remains unchanged and can
still reject commands. Native fallback and control remain unqualified.

## Private state and validation limits

The 1.3.7 ledger contains local attempts/cooldown metadata only; no new secret
storage or vendor quota/reset assumptions. Confirmations, auth and replays all
count; confirmed server consumption and app activity remain unknown. Last-success
timestamps start unknown on restart, and incomplete history is visible. Deleting
private files is not an approved way to bypass a wait or re-enable demand.
The lifetime attempt total is bridge-wide, even when displayed under each
heater. Log `usage_category` identifies confirmation separately; the legacy
per-process status count still includes confirmation reads. Cloud health `ok`
alone is not a freshness guarantee: always check status age and timestamp.

Mocked tests cover coalescing, callback no-I/O, retained/invalid/unknown messages,
spacing, multi-device scheduling, disabled cloud/commands, locks, quotas,
restart barriers, option migration and unchanged auth refresh. Native builds run
the existing isolated MQTT/lifecycle checks plus a network-disabled packaged
worker smoke using synthetic HTTP and zero heater commands. These do not prove
actual HA UI operation, vendor quota sustainability or physical control.

For a later owner-approved trial, use normal Update after reviewing/merging the
PRs, retain the settings above, wait for vendor recovery and start once. Verify
existing entities plus diagnostic age/health/attempt counts before considering
enabling demand. Do not change credentials/generation, issue commands or run a
separate login diagnostic. See PHASE2_CONTROL_DESIGN.md for the later design.
