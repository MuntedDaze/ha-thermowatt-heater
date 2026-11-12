# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.12] - Display name "Thermann Hot Water"

- The app is now shown as **Thermann Hot Water**, with a description that
  states it is unofficial community software, not a Thermann product.
- Nothing else changes: same slug (`thermowatt_boiler`), options, credentials,
  authentication guard, MQTT topics and payloads, entity IDs and command
  behaviour. The bridge code is identical to 1.3.11.
- Listed in `breaking_versions` like every release, so Home Assistant never
  updates it automatically.

## [1.3.11] - Bounded command confirmation for a delayed cloud readback (owner review required)

- **Why.** In T3b (1.3.10) a stale-status `off` was refreshed once and POSTed,
  and the official app then showed OFF, but the single status read made
  immediately after the POST still showed the old mode. 1.3.10 then published
  that read as current and ended the command as
  `not_observed_in_immediate_status`, with no further check: a delayed cloud
  update looked the same as a command that did nothing.
- **Bounded confirmation.** The old mode right after the POST is now
  `awaiting_confirmation`, neither success nor failure. At most **two**
  follow-up status reads are made, **60 s and 300 s** after the POST; any
  background poll in that window also counts. The command is:
  - `observed_in_status` only when a fresh read shows the requested mode (and,
    for `Manual:70`, a 70 °C target);
  - `unexpected_state_after_command` when a read shows neither the old nor the
    requested state (for example an app change);
  - `not_confirmed_within_limit` when nothing confirms it by **360 s** (also
    when reads fail or authentication locks), for owner action.
- **The POST is never repeated**, including after a POST timeout or HTTP error,
  whose outcome is unknown and is observed instead (`awaiting_confirmation`
  with a fixed `error`). An explicit cloud rejection stays `rejected_by_cloud`.
- **One uncertain command at a time.** While a command awaits confirmation
  every other command, including an MQTT redelivery, is refused with no
  request. It is recorded in `refused_while_pending`, so `last_command` keeps
  the pending record.
- **Restart-safe.** The pending command and the last outcome are written to a
  private `command_state.json` **before** the POST. A restart never re-sends
  it; the next reads (or the deadline) decide it. If that file cannot be
  written, the command is refused before any request.
- Diagnostics: `last_command.observed_mode`, `status_reads`,
  `followups_done`, `posted_at`, `confirm_by`; `command_confirmation_pending`,
  `command_confirmation_followups_seconds` (`[60, 300]`) and
  `refused_while_pending`.
- Worst case per command: 5 requests (pre-command read, POST, 3 reads). The
  30-minute polling, `Cmd` 8 OFF mapping, 70 °C rules, automation allowlist,
  authentication guards, lockouts, refresh budget and `commands_enabled: false`
  default are unchanged.

## [1.3.10] - Actual OFF code and bounded pre-command status refresh (owner review required)

- **OFF is `Cmd` 8.** T3 on the owner's heater showed software OFF reports
  `Cmd` 8 (`WaterHeaterSts` 32) with `T_SetPoint` still 70; Manual 70 reports
  `Cmd` 9 (`WaterHeaterSts` 33). 1.3.9 only knew `Cmd` 16, so OFF showed as
  Unknown and a successful `off` was reported `not_observed_in_immediate_status`.
  `Cmd` 8 and 16 are now both OFF for the vendor-mode sensor, the Home Assistant
  water-heater mode (`off`), status validation, `off` confirmation and the
  guarded `Manual:70` rule. `Cmd` 16 is kept for compatibility (unobserved).
  No other code is treated as OFF. `WaterHeaterSts` stays a raw, unverified
  value; it is not used as element feedback.
- **Pre-command status refresh.** A command still needs status no older than
  60 s. When the confirmed status is older, the bridge now makes **at most one**
  bounded status read for that command (counted as `command_refresh`) instead
  of dropping it as `dropped_status_older_than_60s`. Before that read it checks,
  with no request: configuration, MQTT, queue age (≤30 s), device identity,
  command policy, command text, authentication guard, cloud quota/backoff,
  60 s spacing since any status read and a limit of 24 refreshes per rolling
  24 h. Every target and owner-override rule is then evaluated against the new
  status. A failed read is never followed by the command, gets the ordinary
  status-read backoff, and is reported (`refused_status_refresh_failed` with a
  fixed error code). A command older than 75 s after the read is dropped.
- **Mode re-check (automation policy).** Because a controller's view may now be
  up to one poll old, the fresh status must still show the state the command is
  meant to leave: `Manual:70` only from OFF (target 70 or unusable), `off` only
  from Manual 70 °C. Schedule, Eco, Holiday, an unknown code, or Manual at
  another target is the owner's choice and is refused with no request
  (`refused_mode_mismatch` / `refused_target_mismatch`). This also applies to
  the Home Assistant water-heater *off* button. `legacy` keeps the 1.3.9 rules.
- **No duplicate writes.** `off` when already OFF and `Manual:70` when already
  Manual 70 send nothing (`already_in_requested_state`). A status read made for
  a command counts as the ordinary poll if one falls due in the same tick.
- Diagnostics: `last_command.status_refresh`
  (`not_needed`/`refreshed`/`failed`/`refused`), optional `last_command.error`,
  `command_status_refreshes_24h` and `command_status_refresh_limit_24h`. The
  request ledger gains a `command_refresh` category; an older ledger is upgraded
  with its counts kept.
- Unchanged: authentication, token refresh, the persistent 401/403/429 lockout,
  the 30-minute polling default, the optional demand refresh (still off), the
  automation allowlist, no retries, entity IDs, and `commands_enabled: false`
  by default. Changes heater-command handling: owner approval required to merge.

## [1.3.9] - Guarded Manual command for a local executor (owner review required)

- New `command_policy` option, default **`automation`**: only `MODE=Manual:70`
  (heating permitted) and `MODE=off` (parked) are accepted. Every other command
  (temperature writes, Eco, Auto/Schedule, plain Manual, Holiday, malformed) is
  refused before any cloud request, as `refused_by_policy`. `legacy` restores
  the 1.3.8 command set only when chosen explicitly. Monitoring is unchanged.
- Add MQTT `MODE` payload `Manual:70`. It sends `T_SetPoint` 70 explicitly and
  is accepted only when the fresh observed status (≤60 s) already shows 70 °C,
  or shows software **OFF** (`Cmd` 16) with no usable setpoint (outside
  20–75 °C). A usable setpoint other than 70, OFF included, is refused with no
  request (`refused_target_mismatch`): it is never silently changed to 70.
- While OFF, a reported setpoint outside 20–75 °C no longer fails the poll (it
  would otherwise back the bridge off while the heater stays off); it is
  published with `setpoint_valid: false`. Outside OFF the 1.3.8 validation is
  unchanged. Plain `Manual` refuses an invalid observed setpoint
  (`refused_setpoint_unavailable`) instead of sending it.
- Publish `commands_enabled` and a `last_command` record (fixed result codes:
  dropped/refused/rejected/submitted/observed/not observed, no bodies) in the
  existing diagnostics topic, so a dropped stale command is visible without an
  extra cloud read.
- No change to authentication, token refresh, lockouts, polling, request
  accounting, freshness limits, retries (still none) or defaults:
  `commands_enabled` remains false. Changes heater-command handling, so this
  PR requires explicit owner approval before merge; deployment is separate.

## [1.3.8] - Phase 1 dependent review candidate

- Add optional `on_demand_refresh_enabled`, disabled by default. Non-retained
  `P/<serial>/refresh` with payload `refresh` requests a known-device read in the
  existing worker; the MQTT callback performs no HTTP/authentication.
- Coalesce duplicate requests, enforce five minutes after any status attempt,
  and discard requests during auth lockouts, error cooldowns, disconnection or
  incomplete accounting. Never use demand reads as recovery probes or immediate
  retries. Per-device background deadlines avoid redundant reads/starvation.
- Retain authentication/command implementations and all freshness guards.
  Restore exponential ordinary-error history after restart even when its wait
  expired; healthy local cooldown state remains separate from authentication.
- Extend upgrade fixtures from released 1.3.6 with custom saved intervals and
  add mocked demand/permission/multi-device tests plus a packaged-image smoke
  test with no network, synthetic HTTP and zero heater writes.
- Document Smart polling as a slow-background/explicit-demand pattern, not an
  automatic solar-triggered mode. Phase 2 remains design only. Owner review of
  both dependent PRs is required; neither is merged or deployed by the agent.

## [1.3.7] - Phase 1 review candidate

- Add a Seconds/Minutes selector and clearly labelled single polling value,
  validated to 60–7200 seconds. Retain the historical numeric YAML key and use
  Minutes when units are absent, preserving existing 1.3.6 configurations.
- Classify the exact JSON `error` phrase `Daily request limit exceeded`, even
  with HTTP 200. Preserve unrelated diagnostic codes and the existing persistent
  operator lockout on HTTP 429; do not infer vendor limits or reset times.
- Persist private local attempt totals in six categories, including confirmation
  reads, and ordinary error cooldowns. Best-effort accounting cannot authorise or
  deny authentication/commands; incomplete history is explicitly reported.
- Retain ordinary failure history when restarting after an expired cooldown;
  another failed read continues exponential backoff until a successful cycle.
- Add read-only diagnostic sensors for last successful poll, status age, cloud
  health, last known fixed error and local lifetime request attempts. Retain all
  existing entity IDs and unverified physical-heating state.
- Review the requested forks without copying source files, and document Phase 2
  solar/comfort/control design separately. No heater controls or optimiser added.
- Add mocked upgrade/privacy/quota/diagnostic coverage, strict type checking for
  the new support module, Supervisor validation and native container checks.
  Owner review is required; no automatic merge, deployment or live API testing.

## [1.3.6] - 2026-11-09

- Add `poll_interval_minutes` (whole minutes, 5–120), defaulting to 30 both in
  Supervisor configuration and when older saved options omit the key.
- Add `min_cloud_retry_minutes` (5–1440), default 60. Ordinary errors, including
  `cloud_success_false`, wait at least both intervals and use bounded exponential
  backoff (24-hour ceiling) instead of five-minute retries.
- Log configured intervals, error backoff and fixed-category HTTP-attempt counts
  since startup. Include login/refresh, discovery, status, command writes and
  confirmation reads without secrets. Counts reset on restart; no vendor quota
  or reset window is assumed. Defer an enforced persistent daily budget.
- Keep authentication retries, tokens, cooldowns and persistent lockouts unchanged.
  Retain the existing command-loop cadence, read-after-command behavior and all
  freshness/safety guards; command permissions remain separate and disabled by default.
- Preserve installed credentials, cloud/command flags, generation, private state
  and MQTT identities. Mark 1.3.6 as requiring attention for the slower data cadence.
- Add mocked interval/boundary/failure/recovery/upgrade tests and extend Supervisor
  option and isolated container checks. Document the owner-approved polling trial
  in UPGRADING_1_3_6.md. No quota system, live API test or deployment is added.

## [1.3.5] - 2026-11-09

- Split the read-response envelope diagnostic into fixed codes for a non-object
  body, explicit `success=false`, nonempty `error`, missing `result` and a result
  of the wrong type. No response contents, field values or identifiers are logged.
- Preserve the exact 1.3.4 acceptance rules and first-failure order, including
  optional success flags and empty/false error values. No guessed API forms or
  validation relaxation are introduced.
- Retain authentication, persistent refresh cooldown/lockouts, read backoff,
  heater commands, safety checks, private state/options and MQTT IDs unchanged.
- Add mocked diagnostic/redaction/recovery tests and compare envelope acceptance
  against the released 1.3.4 predicate. Document the next controlled update in
  UPGRADING_1_3_5.md. No live test or Home Assistant deployment was performed.

## [1.3.4] - Controlled-update candidate (2026-11-09)

- Replace hidden `cloud_operation_failed` warnings with allowlisted operation
  and failure codes, distinguishing discovery, status, auth, HTTP, transport,
  response validation and private-storage failures without sensitive logging.
- Distinguish successful password login from token refresh; report recovery
  after a failed cloud cycle. Reused stored tokens do not imply another login.
- Persist a five-minute successful-refresh cooldown in the existing guard
  deadline. A repeated GET 401 during it locks before another refresh, including
  across devices and restarts. Preserve transient retry budgets, existing state
  schema, authentication generation and default-disabled commands.
- Add mocked failure/recovery/redaction and repeated-401 regression tests and
  document why historical warnings cannot establish the actual failing response.
  No live API calls, diagnostic environment or deployment.
- Package the reviewed changes as 1.3.4, retaining the add-on identity, options,
  credentials, tokens, version-1 guard records and all existing MQTT entity IDs.
  Installed cloud/command flags and authentication generation are not reset.
- Add released-1.3.3 synthetic upgrade fixtures, cooldown/session compatibility
  tests and native-container replacement checks for authorised and blocked data.
  Retain the existing 1.3.2 upgrade checks as well.
- Document the controlled Update path in UPGRADING_1_3_4.md. The 1.3.4 attention
  marker highlights the refresh policy change; it does not alter private data or
  settings. No further runtime changes are made during release preparation.

## [1.3.3] - Review candidate (2026-11-09)

### Read-only Thermann update (not deployed)

- Record owner-reported temperature agreement at 17°C current / 70°C target,
  app 3.15.17, heater 07.00.09.06 and Wi-Fi 01.03.21.
- Preserve water-heater IDs and native Unknown for Schedule/Holiday; add one
  read-only Vendor mode sensor, mapping inherited Cmd 17 to Schedule with raw
  Cmd/WaterHeaterSts attributes. New unknown codes retain valid temperatures.
- Preserve the heating binary-sensor ID, but report Unknown and JSON null for
  unverified physical heating instead of decoding bit zero. Ignore old retained
  booleans so they cannot perpetuate a false physical-state claim.
- Review existing commands, manufacturer guidance, schedule/diagnostic limits
  and a staged future test plan. No command/authentication changes, additional
  cloud requests, schedule edits or Windows diagnostic workflow.
- Add mocked mode/status/Jinja/command-contract coverage and extend isolated
  container discovery checks.

### Upgrade compatibility

- Bump the existing add-on to 1.3.3 without changing its slug, options/schema,
  option defaults, state paths, authentication code or existing MQTT entity IDs.
- Preserve installed credentials, saved tokens, consumed retry generation,
  lockouts and cloud/command settings. An interrupted authentication remains
  fail-closed; upgrading is not an authentication reset.
- Mark 1.3.3 as requiring attention because the heating sensor intentionally
  changes to Unknown/null. Existing data/options are retained; this marker does
  not enable or reset settings. New-install cloud and command defaults stay false.
- Add actual-1.3.2-format synthetic upgrade fixtures, option/state compatibility
  tests and native-container replacement checks with preserved private data.
- Document the normal Update path and limits in UPGRADING_1_3_3.md. No feature,
  command, schedule, live cloud test, merge or deployment is added.

## [1.3.2] - Previously installed baseline

### Security and authentication

- Validate login/refresh HTTP status, JSON envelopes and token fields instead of
  assuming every HTTP success contains `result`.
- Persist authentication intent, lockouts, retry budgets and deadlines in private
  `/data`; require a new operator retry generation after rejection, unknown
  responses, interruption or exhausted transient retries.
- Never fallback to password login after refresh rejection or unrelated failures.
  Keep the process alive while locked to prevent Watchdog authentication loops.
- Preserve TLS verification, add timeouts, disable redirects, and remove raw
  response/exception logging and credential command-line arguments.
- Remove unused bundled private key/certificates and their image copies. The key
  remains exposed in Git history; issuer review/revocation is still required.

### Reliability and compatibility

- Default cloud access and commands to disabled, manual boot, and mark 1.3.2 as
  a breaking version. Retain supported Supervisor options and MQTT service discovery.
- Back off cloud failures without re-login; reject retained, stale and invalid
  commands; serialize HTTP work and never replay writes.
- Replace optimistic/fake state updates with validated, allowlisted cloud status
  and MQTT availability. Preserve existing entity IDs.
- Use supported MQTT heater modes (`off`, `eco`, `performance` for Manual).
  Disable invented Holiday end dates;
  temperature changes require fresh Manual status and preserve mode.
- Retain HA base 3.24, use a Python virtual environment and pinned direct
  dependencies; remove unsupported armv7 advertisement.
- Add offline HTTP/socket-blocked tests, static checks and safety documentation.
- Add an explicit standalone one-login diagnostic for later owner approval. It
  never retries, starts MQTT, persists tokens, polls or controls a heater.
- Validate native amd64/aarch64 image builds, installed dependencies, actual
  S6/Bashio startup, isolated authenticated MQTT, clean shutdown and restart in CI.
  Disabled cloud/commands produced zero HTTP attempts despite synthetic commands.
- Validate app configuration/options with official Supervisor 2026.10.5 and
  2026.11.0 schemas without running a Supervisor daemon. Record evidence and
  remaining real-HA installation checks in DEPLOYMENT_READINESS.md.

### Owner-reported verification — 2026-11-09

- Owner reports successful 1.3.2 installation and Thermann Control authentication
  in Home Assistant OS, MQTT heater discovery, and current/target temperature and
  heating-status display with cloud enabled and commands disabled.
- Additional Windows login diagnostic cancelled; its uncommitted implementation
  was discarded. No further authentication or runtime changes were introduced.
- Temperature accuracy, operating-mode mapping and heater commands remain
  unverified. Further development is paused for owner review.

### Release limits

- Initial authentication/read-only operation now has an owner success report;
  universal account compatibility, temperature accuracy, mode mapping and actual
  control behaviour are not established. No endpoints or app identities were guessed.
- No agent live requests or physical heater-control tests. Remaining validation
  needs owner review. Anti-legionella protection, thermostat limits and fallback
  schedules must be preserved; Off's effect on those protections is unverified.

## [1.3.1] - Previously published

- Retained HTTPS certificate verification and corrected the Home Assistant Docker
  base image. Authentication retry safeguards were not present in this version.

## [1.3.0] - 2026-01-27

### Removed

- AWS MQTT bridge for real-time status updates
- Certificate-based AWS IoT authentication

### Added

- Added polling loop to avoid rate limiting issues

### Fixed

- Rate limiting issues from frequent API polling, by performing polling in the correct, acceptable way.

---

## [1.2.0] - 2026-01-25

### Added

- AWS MQTT bridge for real-time status updates (replaces polling)
- Support for multiple devices with per-device AWS MQTT clients
- Certificate-based AWS IoT authentication
- Command cooldown mechanism to prevent stale status updates after commands

### Changed

- Commands now use REST API (matching app behavior)
- Status updates come from AWS MQTT instead of polling
- Removed polling loop to avoid rate limiting issues
- Updated status format handling to match AWS MQTT format

### Fixed

- Rate limiting issues from frequent API polling
- Status update cooldown after commands to prevent stale values overwriting optimistic updates

---

## [1.1.1] - 2026-01-24

### Changed

- Polling interval set to 60 seconds
- Updated HomeAssistant mode names to match app behavior

---

## [1.1.0] - 2026-01-24

### Changed

- Upgraded to support breaking backend changes observed after the release of app version 3.14

---

## [1.0.0] - 2026-01-18

### Added

- Initial release
- Basic MQTT bridge functionality
- Home Assistant discovery integration
- Support for temperature and mode control

---

[1.2.0]: https://github.com/waterheater-dev/ha-thermowatt-heater/compare/1.1.1...1.2.0
[1.1.1]: https://github.com/waterheater-dev/ha-thermowatt-heater/compare/1.1.0...1.1.1
[1.1.0]: https://github.com/waterheater-dev/ha-thermowatt-heater/compare/1.0.0...1.1.0
[1.0.0]: https://github.com/waterheater-dev/ha-thermowatt-heater/releases/tag/1.0.0
