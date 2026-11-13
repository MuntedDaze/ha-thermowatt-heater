# Controlled update from 1.3.4 to 1.3.5

This is a diagnostic-only release. The owner reports successful token refresh
followed by `operation=status_poll code=cloud_response_unrecognised` on 1.3.4.
Version 1.3.5 identifies the failed envelope check with a fixed code:

| Code | Meaning |
| --- | --- |
| `cloud_envelope_not_object` | Decoded response is not an object. |
| `cloud_success_false` | The success flag is explicitly boolean false. |
| `cloud_error_nonempty` | The error field is nonempty/truthy under the existing rule. |
| `cloud_result_missing` | The result key is absent. |
| `cloud_result_wrong_type` | The result exists but is not an object, including null. |

Only the first failed check is reported, in the order above. Invalid JSON still
reports `cloud_invalid_json`. A missing success flag or empty/false error field
retains its original acceptance behavior. The same helper validates discovery
responses, so use the accompanying operation code to distinguish the endpoint.
No response contents, field values or unexpected key names are logged.

## What stays unchanged

The acceptance rules are identical to 1.3.4. The source expects named status
fields inside an object result; there is insufficient evidence to accept a
different shape safely. This release diagnoses the check, not the underlying
vendor response or a proven compatibility fix.

Authentication, tokens, five-minute refresh cooldown, lockouts, transient retries,
read backoff, commands and safety behavior are unchanged. The same add-on slug,
option schema/defaults, private state format/paths, device identity and all MQTT
entity IDs remain. Existing credentials, tokens, cooldown/retry deadlines,
authentication generation and configured cloud/command flags are retained.
In-flight authentication continues to fail closed on restart, as before.

No new `breaking_versions` attention marker is needed for a diagnostic-only
change; the existing 1.3.2/1.3.3/1.3.4 markers remain. There is no migration,
credential re-entry, generation increment or guard reset for this update.

## Next owner-controlled installation

After reviewing the merged release and approving installation yourself:

1. Use the existing add-on's normal **Update** action to obtain 1.3.5; do not
   uninstall/reinstall, replace options or delete private data. Retain the normal
   private backup without sharing it because it contains secrets.
2. Confirm the version and existing options. Retain the configured cloud flag,
   keep `commands_enabled=false`, and leave credentials/authentication generation
   unchanged. Do not reset a lockout or restart repeatedly to gather messages.
3. During ordinary read-only operation, check for the new
   `operation=status_poll code=...` pair and report only that fixed pair. Do not
   copy JSON, field values, response bodies, identifiers, tokens or credentials.
   Do not trigger a separate diagnostic login.
4. If the existing cooldown or lockout guard pauses the bridge, leave it paused
   for review. This diagnostic update must not be used to bypass that guard.

This installation procedure was not executed. No live cloud request,
authentication, Home Assistant access or heater operation occurred in development.

## Validation

All previous tests remain, including authentication/cooldown, disabled commands,
private data/options and MQTT-ID preservation. New mocked tests cover every
envelope code, first-failure order, log redaction, unchanged guard bytes,
read-only recovery and differential acceptance against the old predicate.
Native amd64/aarch64 CI builds and isolated MQTT lifecycle/preserved-data checks,
plus official Supervisor schemas, are release gates. See the release PR's
final-head CI for results. No actual Supervisor upgrade, live response schema
or physical heater behavior is claimed as independently verified.
