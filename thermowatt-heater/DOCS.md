# Thermowatt bridge 1.3.3 — review candidate

This is the proposed update from the owner's working 1.3.2 installation. See the
[upgrade notes](../UPGRADING_1_3_3.md): the existing slug, options, private data and
old entity IDs are retained. Updating does not reset the authentication guard or
change installed cloud/command settings. No new features are added during release
preparation, and PR #2 remains draft and unmerged.

Cloud access and heater commands default to disabled. Installation alone does not
authorise authentication. Keep both disabled while reviewing this candidate.
The agent's development checks used no live account, cloud API, physical heater
or owner's Home Assistant/Docker installation. Container checks ran only on
disposable CI runners. The later owner-reported result is recorded below.

## Owner-reported initial read-only success — 2026-11-09

The owner reports that 1.3.2 is installed and running in the Home Assistant OS VM,
has authenticated directly with the recovered Thermann Control account, and has
discovered the Thermann heater through MQTT. Home Assistant displays current
temperature, target temperature and heating status. The reported configuration
is `cloud_enabled: true`, `commands_enabled: false`.

The owner subsequently reports matching app/heater and HA readings of 17°C
current and 70°C target, with app 3.15.17, heater 07.00.09.06 and Wi-Fi 01.03.21.
HA's Unknown mode corresponds to the app's Schedule label; its Heating: Normal
display is not verified physical feedback. These are owner observations, not a
live test by the agent or independent temperature calibration. No HA commands
have been tested. The cancelled Windows workflow remains unnecessary.

The proposed small read-only follow-up is described in the repository's
[compatibility/control review](../THERMANN_CONTROL_REVIEW.md). It adds a Vendor
mode sensor and makes the unverified physical heating state explicitly unknown.
No authentication changes, live requests, heater commands or schedule changes
are made for this review. Control testing and automation await separate approval.

Later command assessment must preserve anti-legionella protection, thermostat
limits and the existing fallback schedule. Whether Off preserves these
protections is unverified. EMHASS/solar/tariff optimisation and the 7 am/~4 pm hot
water objectives remain later stages, after read-only validation and individual
verification of the existing API commands.

## Account compatibility and the original failure

The existing bridge targets the **MyThermowatt** app contract: the existing
`https://myapp-connectivity.com/api/v1` base URL, `/login` and `/refresh`, and
`app: MyThermowatt` / `version: 3.14` headers. The legacy implementation assumed
every HTTP-success login contained `result.accessToken` and `result.refreshToken`.
An error envelope with HTTP 200 therefore raised `KeyError: 'result'`. Startup
called `sys.exit(1)`, allowing Watchdog to repeat the same password login every
restart. Polling also called login after unrelated HTTP errors and exceptions.

The reported message proves the response did not match that assumed schema. It
does **not** identify the vendor's reason, prove invalid credentials, or prove
that this integration caused a vendor lockout. No sensitive response is needed
to diagnose the unsafe retry path.

[Thermann's Smart Electric owner's guide](https://www.thermann.com.au/thermann-cms/files/Thermann-Smart_Electric-Owners_Guide.pdf)
instructs users to create an account in Thermann Control.
[Thermowatt's MyThermowatt description](https://www.thermowatt.com/en/news/2022-11-mythermowatt-new-features.html)
describes its TMEC Wi-Fi product. These public sources do not establish shared
account namespaces, app identifiers, API keys, endpoints, or token schemas.
There is useful but limited first-hand evidence:
[upstream issue #7, posted 2026-04-09](https://github.com/waterheater-dev/ha-thermowatt-heater/issues/7)
reports that an Australian Thermann unit worked with Thermann Control credentials
and the unchanged add-on/backend. The same owner also
[reported receiving MQTT data](https://community.home-assistant.io/t/smart-immersion-heater-thermowatt/656332/9).
These are that owner's observations, not vendor API documentation; the exact
model, account region and authentication response were not supplied. No Thermann
alternative API or account-specific contract was found in the local source or
upstream code search. The current owner has since reported successful initial
authentication and read-only operation for the Australian Thermann Smart Electric
315 L, as recorded above. This does not establish universal account compatibility
or verify heater controls. No endpoints or app identities were guessed. Cloud
access remains disabled by default; the owner's current read-only installation
uses cloud access enabled and commands disabled.

## Configuration

Use the add-on Configuration tab. Supervisor supplies resolved options through
`/data/options.json`, including supported `!secret` references. Credentials are
never passed as command-line arguments.

```yaml
email: ""
password: ""
cloud_enabled: false
commands_enabled: false
auth_retry_generation: 0
```

- `cloud_enabled`: explicit permission for this installed instance to use the
  existing MyThermowatt API. Missing options also default to false on upgrade.
- `commands_enabled`: separate permission for MQTT commands. Leave false for
  read-only observation. This does not establish Thermann compatibility.
- `auth_retry_generation`: a monotonically increasing, non-secret integer. Zero
  starts locked. Increasing it authorises one authentication cycle. The accepted
  generation is persisted; leaving the same value configured cannot reset a
  subsequent lockout. Lowering it, changing a password, restarting, updating, or
  toggling Watchdog does not clear an existing lockout. Changes apply at restart.

An owner-approved first MyThermowatt trial would set cloud access true and change
generation 0 to 1, with commands still false. **Do not use the normal polling
service to investigate a currently locked or unverified Thermann account.**

## Diagnose authentication safely

1. Stop other copies/older versions of this bridge. Do not repeatedly restart
   older versions or repeatedly test the password in different apps.
2. Record only the fixed diagnostic code, add-on version and app/account brand.
   Do not post options, bearer tokens, API keys, response bodies, private files,
   or unredacted network captures.
3. `auth_http_401` / `auth_http_403`: rejected authentication. Confirm account
   eligibility/activation and any vendor lockout with official support.
   `auth_http_429`: rate limit; the local guard stays locked indefinitely even if
   a vendor cooldown expires. No automatic retry follows a Retry-After header.
4. `auth_response_unrecognised`: HTTP 200 with missing/invalid tokens, absent
   `result`, invalid JSON, or a different envelope. This is a compatibility or
   backend-response problem; do not infer a new endpoint from it.
5. `auth_tls_error`: certificate verification failed. Check the system clock and
   trusted CA installation. Never disable verification.
6. `auth_retry_exhausted`: three transient auth attempts failed. Timeouts,
   connection failures and HTTP 5xx receive at most three attempts per cycle,
   spaced by at least 60 then 300 seconds. Attempt counts and deadlines persist.
   No password fallback follows a refresh failure. Other auth statuses, redirects
   and unknown responses lock immediately after one request.
7. `interrupted_auth`: the process stopped after an attempt was recorded and
   before the outcome was safely stored. Its outcome is unknown, so retry needs
   operator approval. `storage_invalid` / `guard_storage_unavailable`: keep cloud
   disabled and repair private persistent storage before authorising any retry.

For ordinary cloud outages, the bridge marks entities unavailable and backs off
up to 300 seconds. It does not re-login for server errors, malformed device/status
responses, zero devices, local MQTT outages, or programming errors. A GET 401 can
refresh once and replay that read once; a second 401, any 403 or 429 locks cloud
access. A command POST is never replayed or followed by password fallback.

## Safely clear a local lockout — explicit owner action

This procedure clears only the local guard; it cannot unlock a vendor account.

1. Keep `cloud_enabled: false` until the vendor confirms the account is unlocked,
   the correct app/API is supported, and the owner approves one new trial.
2. Stop the add-on. Correct the configuration if needed. Keep
   `commands_enabled: false`.
3. Set `auth_retry_generation` to a **new larger integer** than every previously
   accepted value (for example, 1 to 2). After approval, set cloud access true,
   save and start the add-on once.
4. If the request is rejected or unrecognised again, leave the resulting lockout
   intact and return to vendor support. Do not automate generation increments.

Do not delete `/data/auth_state.json` as a routine reset. It contains the consumed
generation, guard, deadlines and private tokens. Corrupt guard data is replaced
with a blocked state consuming the current configured generation; after repairing
storage, a later increase is needed. Uninstalling, discarding `/data`, or restoring
an older backup can discard newer safety state. Keep cloud disabled during such
operations and review the generation before any restart. No software guard can
survive removal or rollback of its persistent storage. Run one bridge instance
per account; independent installations cannot coordinate lockouts.

## MQTT states and commands

Existing water-heater and heating-sensor discovery topics and unique IDs remain.
Both entities require bridge and device availability. Only validated cloud status
updates state; errors never inject zero temperatures, Off modes or fake setpoints.
Only audited status fields are published, not arbitrary cloud response bodies.

Home Assistant's MQTT water heater accepts a fixed set of operation modes. The
previous custom uppercase modes were incompatible with its current schema.
`off`, `eco`, and `performance` now represent Off, Eco, and Manual. Auto/Holiday
show unknown on the water-heater mode field rather than a misleading supported
mode; their numeric `Cmd` is retained in the published status. Use the existing
Thermann app for schedules. One read-only Vendor mode sensor now labels Cmd 17
as Schedule; it also exposes raw Cmd and WaterHeaterSts with heating interpretation
marked unverified. Unknown nonnegative mode codes keep valid temperature data
available. No new controls or cloud endpoints are added. Existing
automations using uppercase heater modes need review. The existing explicit
MQTT `MODE=Auto` command remains gated by `commands_enabled`; it activates the
legacy `/auto` route intended for the stored schedule. Its effect on this unit
and preservation of the program have not been tested.

The existing heating binary sensor retains its ID/topic but is labelled
unverified and reports Unknown for every status code, including old retained
heating booleans. No verified `WaterHeaterSts` bit definition was found. The
published `result.heating` is null; consumers must not interpret it as false or
as proof of an unpowered element. Use the raw value for later reviewed diagnosis.

Commands are queued on the MQTT callback and executed serially by the main loop.
Retained commands are rejected, including retained writes while connected using
MQTT v5 retain-as-published. Stale/unknown commands and commands while unavailable
are discarded. Temperature must be a whole number from 20–75 C and is accepted
only when fresh status confirms Manual mode: the existing `/manual` operation also
changes mode, so using it from another mode would be a hidden side effect. Manual
mode uses the last observed setpoint, never an invented default. Holiday writes
are disabled because the old code silently invented a 30-day end date. The
generic software range is not a verified Thermann operating envelope; resolve
model-specific limits before authorising commands. The detailed review records
manufacturer guidance and the remaining Off/resume/fallback uncertainties.

A successful HTTP command status means only that it was submitted. The next
validated status is published and the requested value is compared to observation.
A mismatch is reported as unconfirmed; timeouts are uncertain and never retried.
Even a matching cloud status is not a hardware acknowledgement or proof that a
particular command caused it. Read-only approval does not authorise commands.

## Current Home Assistant compatibility review (2026-11-09)

This is a Supervisor-managed add-on (now called an app), for Home Assistant OS on
`amd64` / `aarch64`. Home Assistant Container does not provide Supervisor apps.
32-bit `armv7` was removed from the advertised architectures because current HA
and its base images no longer support it.

The Dockerfile retains `ghcr.io/home-assistant/base:3.24`, uses its S6 init
(`init: false`), installs CA certificates, and isolates pinned direct Python
dependencies in a virtual environment. MQTT uses the supported `mqtt:need`
Supervisor service and Bashio service discovery. No privileged mode, host
network, host mappings or new Supervisor permissions are requested. The obsolete
top-level `mqtt: true` key was removed in 1.3.2. Boot defaults to manual; 1.3.2 and
1.3.3 are marked as attention-requiring versions. For 1.3.3 this highlights the
intentional heating-state change to Unknown/null, without resetting installed
options, credentials or private data.

Sources reviewed:
[configuration](https://contributors.home-assistant.io/apps/reference/configuration/),
[options and secrets](https://contributors.home-assistant.io/apps/guides/options/),
[persistent data and Watchdog](https://contributors.home-assistant.io/apps/how-apps-work/),
[base images](https://github.com/home-assistant/docker-base),
[supported architectures](https://www.home-assistant.io/more-info/unsupported/system_architecture/),
[MQTT water-heater modes](https://www.home-assistant.io/integrations/water_heater.mqtt/).

Native amd64 and aarch64 builds, installed dependencies, actual S6/Bashio startup,
isolated authenticated MQTT, clean shutdown and restart have now passed in CI.
The actual validators in official Supervisor 2026.10.5 and 2026.11.0 images also
accepted the configuration/options. The cloud-disabled tests recorded zero HTTP
attempts and could not issue heater commands. See the repository's
[deployment-readiness report](../DEPLOYMENT_READINESS.md) for evidence and limits.
No full Supervisor daemon, HA OS installation or HA Core discovery/UI validation
was run. Those remain owner-approved installation checks, not assumed passes.

## Offline development checks

```shell
python -m venv .venv
# Activate .venv using your platform's normal activation command.
python -m pip install -r requirements-dev.txt
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m compileall -q thermowatt-heater tests
```

Dependency installation uses PyPI; the test suite itself blocks sockets, DNS and
unmocked Requests calls. Every HTTP response and credential in tests is synthetic.
Restart tests reconstruct bridges from the same temporary persistent data.

## Optional standalone diagnostic — not needed for the current owner

The owner has already authenticated through the add-on. This older reference
procedure is not the next verification step and should not be run for this task.
The additional Windows diagnostic workflow was cancelled; no such workflow was
added to the integration.

**Not executed during development. This sends a real login when deliberately
invoked. Do not use it while the vendor account is still locked.** It tests only
the existing login response, not heater discovery, control or full compatibility.

1. Obtain explicit owner approval for one login after the account has recovered.
   Stop all old bridge instances. Confirm the expected app/account identity with
   official support if it remains uncertain; do not test alternative endpoints.
2. Use this reviewed checkout and its Python environment on an isolated machine.
   Do not alter Home Assistant or Docker to run the diagnostic. Create a private
   persistent directory outside the checkout (directory mode 0700 and file mode
   0600 on Linux, equivalent owner-only ACLs on Windows). Keep its guard between
   runs; do not put it in Git, shared storage or CI.
3. With a secure local editor create `options.json` in that directory. Supply
   the account email/password there, `cloud_enabled: true`,
   `commands_enabled: false`, and `auth_retry_generation: 1` for a new directory.
   Use JSON syntax. Never put credentials in command arguments or paste them
   into a support chat. For an existing diagnostic guard, a later run requires
   a larger generation and a new explicit approval.
4. Run once, manually, from the checkout:

   ```shell
   python tools/diagnose_auth.py --allow-single-login --data-dir "<private-directory>"
   ```

   Do not put this command under Watchdog, a scheduler, a retry wrapper or CI.
   It sends **at most one POST to the existing `/login` endpoint**. It never
   follows redirects, refreshes a token, discovers devices, starts MQTT, polls,
   or sends heater commands. Even network failures and 5xx lock immediately in
   this mode. A successful token pair is validated then discarded; the guard is
   locked before exit. An interrupted request also locks on the next startup.
5. Record only the fixed outcome code. Accepted authentication establishes only
   that this response matches the legacy token schema. Any later read-only device
   trial needs separate approval. Rejection, rate limiting or an unknown response
   ends the experiment; do not increment the generation and try again automatically.

If this fails after account recovery, further progress likely needs vendor API
details or app reverse-engineering to determine app identity, token schema and
account routing. That is outside this modest repair. The practical fallback is
the existing Thermann Control app and its scheduling, while asking the vendor
for a supported integration. Any external switching/control alternative should
be assessed with the manufacturer and a qualified installer, preserving the
heater's safety controls; this project does not implement one.

## Cloud failure diagnostics

The follow-up diagnostics change distinguishes password login
(`auth_login_accepted`) from token refresh (`auth_refresh_accepted`). Reusing a
stored session does not emit another authentication-accepted message. Warnings
now identify a fixed operation and code, for example
`operation=status_poll code=cloud_invalid_json`, instead of hiding the cause as
`cloud_operation_failed`. Neither response bodies nor raw exceptions are logged.

A second GET 401 within five minutes of successful refresh locks persistently
before another refresh (`cloud_refresh_cooldown`, stored reason `cloud_http_401`).
The deadline survives restarts; ordinary successful reads remain permitted.
Existing auth retry budgets and lockout protections remain in place. Keep
commands disabled and do not change the authentication generation or delete
state to diagnose this warning. See the
[diagnostic review and code table](https://github.com/MuntedDaze/ha-thermowatt-heater/blob/main/CLOUD_DIAGNOSTICS.md).
Old generic messages alone cannot identify the actual cloud failure.

## Release decision

1.3.3 remains a **review candidate**. The owner reports a successful real HA OS
1.3.2 installation, authentication and initial read-only status display. This is not
approval for heater commands, automation, merging or general release. Keep the
owner's commands disabled while the remaining functionality is reviewed. See the
deployment-readiness report for unverified areas and the security review for the
historical private key and token-storage risks. No further development is planned
until owner review.
