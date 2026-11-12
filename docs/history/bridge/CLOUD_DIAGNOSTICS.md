# Cloud failure diagnostics and polling

The 1.3.7 review candidate adds exact JSON `error` classification as
`cloud_daily_limit`, persistent private local attempt counts/cooldowns and
read-only freshness/health diagnostics. See [upgrade notes](UPGRADING_1_3_7.md).
HTTP 429 still locks the original authentication guard; no vendor quota or reset
time is inferred. Near-match text and unrelated errors retain generic categories.

1.3.5 refined 1.3.4's envelope diagnostic without changing validation or
authentication policies. 1.3.6 adds the owner-approved configurable ordinary
polling interval (default 30 minutes) and minimum ordinary-error retry interval
(default 60 minutes), plus safe per-run request-attempt accounting. See
[UPGRADING_1_3_6.md](UPGRADING_1_3_6.md). No live installation is changed here.

After the diagnostic release, the owner reported `cloud_success_false` and an
official app message that its daily request limit was exceeded. This makes quota
exhaustion a plausible explanation, not a verified mapping of the vendor error.
The public quota, scope and reset window remain unknown; 30-minute polling is
an owner-chosen trial, not a vendor-confirmed safe allowance.

In 1.3.6 successful ordinary cycles use the normal interval. Failed ordinary
cycles use the larger of both configured intervals with exponential backoff and
a 24-hour ceiling, measured from cycle completion. This
includes discovery, status transport/HTTP failures and envelope/field validation
failures. The former five-minute ordinary-error loop no longer applies at the
30-minute default. Authentication retries and GET 401 refresh/replay keep their
existing bounded behavior. Explicit enabled commands and their confirmation
reads are not ordinary polling; command checks and safety guards are unchanged.
See the upgrade notes for timing, startup/restart and stale-state limitations.

The owner now reports `auth_refresh_accepted` followed by
`operation=status_poll code=cloud_response_unrecognised` on 1.3.4. In that code,
this means the status read reached envelope validation after HTTP success and
JSON decoding. It does not identify which condition failed. 1.3.5 distinguishes
the conditions below without logging the body, keys present or field values.

## What the existing messages establish

The owner reports repeated `Authentication accepted; tokens stored privately`
messages followed by `Bridge paused: cloud_operation_failed`, including after
the 19:27 restart with cloud enabled and commands disabled. No live installation,
account or API was accessed in this investigation.

In 1.3.3 both `/login` (password login) and `/refresh` (token refresh) emit that
same acceptance message. It means only that HTTP 200 contained the expected
non-empty token pair; it does not establish successful discovery or polling.
An authorised guard reuses stored tokens on restart without logging acceptance
or sending another password login. Failed cloud reads do not trigger password
fallback. Therefore those old messages cannot identify which authentication
operation occurred, or why a subsequent cloud operation failed.

In 1.3.3 there was exactly one `cloud_operation_failed` producer: the exception handler in
`tick()`. It catches `CloudError`, `OSError`, `ValueError` and `TypeError`. When
the guard is blocked it logs the stored lockout reason; otherwise it discards the
exception's existing diagnostic and emits the generic message. This masks:

- Authentication retry waits, network timeouts/connection errors and HTTP 5xx
  while the guard still has a transient retry budget.
- Discovery and status HTTP failures, TLS/transport errors, invalid JSON,
  rejected or missing result envelopes, malformed device lists and invalid
  status fields/values.
- Command HTTP failures and explicit rejection, when commands are enabled;
  status reads used for command confirmation can also fail. These writes cannot
  explain this installation's report while commands remain disabled.
- Private device-cache storage errors and unexpected value/type errors raised
  during the iteration.

The historical generic warning cannot reveal the actual failing operation. This
change exposes the safe diagnostic on a future owner-approved update; it does
not establish a cloud-side cause from the old logs.

## New fixed codes

Warnings have the form `Bridge paused: operation=status_poll code=cloud_http_503.`
Operation codes are `authentication_guard`, `password_login`, `token_refresh`,
`device_discovery`, `device_cache_storage`, `status_poll` and `heater_command`.
The same operation/code/backoff tuple is suppressed until it changes or a complete
cloud cycle recovers. Warnings include safe `backoff_seconds`, guard mode and
total requests since startup; a locked guard never unlocks on that timer. Each
HTTP attempt logs a fixed category and category/total counts, including failed
attempts and command-confirmation reads. No values from requests or responses
are logged. Counts reset on process restart and are not a vendor daily meter.
Recovery logs `cloud_cycle_recovered` once.

| Code | Meaning |
| --- | --- |
| `auth_login_accepted` / `auth_refresh_accepted` | Password login / token refresh returned the expected token schema. |
| `cloud_timeout` / `cloud_connection_error` / `cloud_network_error` | Read/write timeout, connection failure or other Requests transport failure. |
| `auth_timeout` / `auth_connection_error` | Authentication transient failure; existing persistent retry budget applies. |
| `auth_http_NNN` / `cloud_http_NNN` | Actual HTTP status, restricted to a three-digit status code. Auth 5xx uses the existing bounded transient policy; rejected authentication and cloud 401/403/429 lock as before. |
| `auth_tls_error` / `cloud_tls_error` | Certificate/TLS error; no insecure fallback. |
| `auth_transport_unrecognised` / `auth_response_unrecognised` | Unsupported auth transport or token response; persistent lockout. |
| `cloud_invalid_json` | JSON could not be decoded; unchanged from 1.3.4. |
| `cloud_envelope_not_object` | Decoded response is not a JSON object. |
| `cloud_success_false` | The success flag is explicitly boolean false. |
| `cloud_error_nonempty` | The error field is nonempty/truthy under the existing rule. |
| `cloud_result_missing` | The result key is absent. |
| `cloud_result_wrong_type` | The result exists but is not an object, including null. |
| `device_list_unrecognised` | Missing/malformed device list or invalid serial format. |
| `status_fields_missing` | At least one required status field is missing. |
| `status_values_non_numeric` / `status_values_non_finite` | A required status value cannot be interpreted as a finite number. |
| `status_temperature_out_of_range` | Current or target temperature fails the existing validation limits; limits have not changed. |
| `status_mode_invalid` / `status_heater_state_invalid` | Corresponding raw status code is negative or not an integer. |
| `cloud_refresh_cooldown` | Another GET 401 arrived within five minutes of a successful refresh; guard locked with reason `cloud_http_401`. |
| `command_rejected` | Existing command endpoint explicitly rejected the request; no success state is invented. |
| `private_storage_error` / `guard_storage_unavailable` | Private data could not be stored; no paths are logged. |
| `internal_value_error` / `cloud_error_unclassified` | Unexpected local value/type or non-allowlisted cloud error; raw exception text is discarded. |

Existing fixed guard reasons (for example `interrupted_auth`, `auth_retry_exhausted`
and `storage_invalid`) remain available. No exception traceback, request URL,
serial, account identifier, credentials, token, API key or response body is added
to these messages. Share only fixed operation/code pairs for review. Do not
enable commands, delete private state or increase authentication generation to
collect diagnostics. A lockout remains locked until a separately approved
operator action; restarting does not clear it.

## Envelope validation review

The existing parser consumes `result.T_Avg`, `result.T_SetPoint`, `result.Cmd`
and `result.WaterHeaterSts` for status, and `result.termostati` for discovery.
This supports the current object-result contract in the source. It does not
establish that the vendor always returns that contract, or prove that a direct
status object, list, null result or another envelope is a compatible response.
The owner's new fixed code can locate the failed rule but cannot alone prove
that an alternative shape is safe to accept. No response schema evidence in the
repository justifies loosening validation; no endpoint was probed.

1.3.5 retains the original left-to-right precedence: non-object response,
explicit boolean `success=false`, truthy `error`, missing result, then result
type. Only the first failure is reported. Invalid JSON still uses
`cloud_invalid_json`. Success need not be present or true; an absent/empty/false
error field is still allowed. An empty result object still passes envelope
validation, then fails field validation where appropriate. In particular,
`cloud_error_nonempty` does not mean every mere presence of an `error` key is
rejected. No field values or unexpected key names are included in diagnostics.

Mocked tests compare acceptance with the released 1.3.4 predicate across missing,
null, boolean, numeric, string, list and object field variants. Recovery and
log-redaction tests cover discovery and polling without a new authentication
request or guard-state change.

## Refresh handling (unchanged from 1.3.4)

Previously a GET 401 allowed one refresh and one read replay per request. A
second 401 on the replay already locked persistently, but a successful replay
allowed another successful refresh on the next device or polling iteration;
authentication success reset the attempt counter each time.

A successful refresh now persists a five-minute deadline in the existing
`next_retry` field of the authorised guard. Normal reads remain allowed. Another
GET 401 before that deadline locks before sending a refresh, even across
devices, failed status validation, network/server failures or process restarts.
After the interval, a later ordinary token expiry can refresh once and replay
only its GET. A replayed 401 still locks immediately. This bounds successful
refreshes to at most one per five minutes and stops the usual repeated-poll 401
loop at its second occurrence. No POST command is replayed.

Transient failed authentication retains the existing three-attempt budget and
60/300-second retry delays across restarts. No password fallback, token format,
state schema/path, generation, credentials, MQTT IDs, option defaults or command
enablement is changed. Existing authorised sessions are loaded unchanged;
the new deadline is recorded only after a future successful refresh. The
standalone diagnostic workflow is unchanged and is not needed or invoked.

## Validation limits

Mocked regressions exercise discovery/status/refresh failures, safe diagnostic
codes, log redaction, recovery, duplicate suppression, two-device 401s and
restart-persistent refresh limits. Existing offline safety, authentication,
command-disablement and preserved-data upgrade tests remain in place. Actual
cloud response semantics and this installation's failure cause remain
unverified until safe codes are observed after an owner-approved update.
