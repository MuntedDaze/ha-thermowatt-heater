# Controlled update from 1.3.3 to 1.3.4

1.3.4 packages PR #3's reviewed cloud diagnostics and bounded refresh handling.
Release preparation adds version metadata, documentation and upgrade validation;
it makes no further bridge, authentication or command changes. PR #3 remains
draft and unmerged. Nothing has been installed on the owner's Home Assistant.

## State and option compatibility

| Item | Preserved behavior |
| --- | --- |
| Add-on identity | Same repository folder, `thermowatt_boiler` slug, architectures, launcher, Dockerfile and MQTT service dependency. A normal Update replaces the container and keeps private `/data`. |
| Credentials/options | Same names, schema and defaults. Installed email/password, cloud/command flags and `auth_retry_generation` remain in Supervisor-managed `/data/options.json`; the bridge does not rewrite them. |
| Authorised sessions | Existing access/refresh tokens, account binding and generation in `/data/auth_state.json` remain valid local state. Startup reuses the session without forcing a password login. Actual cloud token expiry/revocation is not tested offline. |
| Refresh deadline | Same version-1 guard format. Old authorised records, including successful-refresh records with `next_retry=0`, load unchanged; the update invents no cooldown or retry. A future successful refresh records its five-minute deadline. An already-saved authorised cooldown is preserved across restarts. |
| Lockouts/retries | Existing blocked records, including `cloud_http_401`, stay blocked even after their deadline expires. Attempt budgets and transient retry deadlines remain. An interrupted in-flight request becomes blocked, as before; uncertain tokens are discarded. |
| Device/MQTT identity | Device UUID and cached serial/name metadata remain in `/data/thermowatt_config.json`. Heater, unverified Heating binary sensor and Vendor mode sensor keep the same discovery topics, unique IDs and device ID. No entities are added. |

For the owner's installed `cloud_enabled=true`, `commands_enabled=false`, the
normal update retains true/false. Other deliberately configured combinations
are also preserved; this is not a configuration reset. New-install defaults
remain false/false. Do not paste example/default options over installed values.

No credential re-entry, token deletion, generation increment or lockout reset is
required by the version change. A blocked session does not become authorised
merely by updating. Private options, tokens, state and backups remain sensitive
and must not be shared or added to Git.

## Reviewed behavior changes

Warnings now identify a fixed operation and failure code instead of hiding it
behind `cloud_operation_failed`. Password login and token refresh successes have
distinct codes. No credentials, tokens, API keys, response bodies or raw exception
messages are logged. See [the diagnostic code table](CLOUD_DIAGNOSTICS.md).

A GET 401 may refresh once and replay only that read. Another GET 401 within
five minutes of successful refresh locks before another refresh, including after
a restart. Normal reads remain permitted during the cooldown. A replayed 401
still locks immediately; existing bounded transient-auth retries remain. There
is no password fallback, command replay or automatic unlock. Updating does not
establish the cause of historical cloud failures; a later fixed code is needed.

1.3.4 is added to `breaking_versions` to require attention to this refresh
policy during a controlled update. This metadata prevents a silent automatic
update; it does not alter installed options, guard generation or private state.
The existing Schedule/Vendor mode and Unknown physical-heating presentation
from 1.3.3 are unchanged. Commands remain unverified on the owner's heater.

## Later owner-approved installation

After review/merge and separate installation approval:

1. Use the existing add-on's normal **Update** action. Do not uninstall/reinstall,
   delete `/data`, replace options or change repository/add-on identity. Retain
   the owner's normal private backup; do not share it because it contains secrets.
2. Leave credentials, authentication generation and cloud/command settings as
   configured. Do not clear a lockout or enable commands as part of the update.
3. Confirm version 1.3.4, retained flags and existing entities. Record only fixed
   operation/code pairs if warnings occur; do not collect response bodies or
   trigger a separate diagnostic login. A stored authorised session is reused;
   ordinary cloud operation still follows the reviewed refresh policy.

This procedure was not executed. No cloud requests, live authentication,
Home Assistant access, heater commands or schedule changes are authorised here.

## Validation scope

Fixtures were generated offline from the released 1.3.3 code at
`fce5458256e8a615d8a935266126892967bdd45f`, using only synthetic credentials,
local guard transitions and mocked MQTT. Upgrade tests cover all cloud/command
flag combinations, authorised login/refreshed sessions, blocked/retry/in-flight
records, token and generation retention, entity identity and persisted cooldowns.
The existing released-1.3.2 synthetic fixture and upgrade tests remain covered.

Native amd64/aarch64 CI builds the actual add-on image and runs isolated MQTT,
startup/shutdown/restart and replacement-container tests with preserved data.
Replacement cases cover authorised login/refreshed sessions and auth/cloud
lockouts from 1.3.3, plus the existing authorised/blocked 1.3.2 cases. Cloud and
commands are disabled in container smoke tests; a test hook prohibits external
HTTP, DNS and socket access. Python tests use mocked HTTP to exercise authorised
cloud reads and refresh handling. Check PR #3's final-head CI for results.

These checks do not execute Supervisor's actual Update operation. Owner HA OS
update/UI behavior, real token validity and physical heater behavior require
separate approved verification and are not claimed as passed.
