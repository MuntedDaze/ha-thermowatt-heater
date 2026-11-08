# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.2] - Review candidate (2026-11-09)

### Proposed read-only Thermann follow-up (not deployed)

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
  container discovery checks. Release numbering/deployment remains owner-reviewed.

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
