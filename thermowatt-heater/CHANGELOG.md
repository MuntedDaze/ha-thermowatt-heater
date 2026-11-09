# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
