# Updating Thermowatt 1.3.9 → 1.3.10, and the supervised validation (T3b)

**Not yet approved. Nothing here has been done.** Merging the PR, installing the
update, enabling commands and the supervised test are four separate owner
approvals.

## Why 1.3.10

T3 (1.3.9, controller 0.6.0) showed two problems:

| Found in T3 | Cause | 1.3.10 |
| --- | --- | --- |
| OFF showed as **Unknown**, and a successful `off` was reported `not_observed_in_immediate_status` | the heater reports OFF as `Cmd` **8**; 1.3.9 only knew `Cmd` 16 | `Cmd` 8 and 16 are OFF everywhere (sensor, HA mode `off`, validation, `off` confirmation, guarded `Manual:70`) |
| Commands were dropped as `dropped_status_older_than_60s` unless sent within a minute of the 30-minute poll | the 60 s freshness rule had no way to obtain fresh status | at most **one** bounded status read per command, then every rule is re-checked against it |

The 60-second rule itself is unchanged: a command is never executed on status
older than 60 s.

### What a command now does

1. Without any request, it is refused unless: commands are enabled, MQTT is
   connected, the command is ≤30 s old, the device is known, the payload is
   `off` or `Manual:70` (automation policy), the authentication guard is
   authorised, the cloud is not quota-limited or in backoff, no status read
   happened in the last 60 s, and fewer than 24 command refreshes happened in
   the last 24 h.
2. If the confirmed status is ≤60 s old, it is used. Otherwise one status read
   is made (request category `command_refresh`).
3. If that read fails (timeout, connection, HTTP error, quota, 401/403/429), the
   command is **not** sent and not retried. It is reported as
   `refused_status_refresh_failed` with a fixed `error` code, and the ordinary
   status-read backoff applies. The existing authentication lockout is
   unchanged.
4. The command is re-validated against the new status:
   - `Manual:70` is refused if a usable target other than 70 is shown (OFF
     included), so the owner's own setting is never overwritten;
   - nothing is sent if the heater is already in the requested state;
   - it is dropped if it became older than 75 s during the read.
5. POST, then one confirmation read, as before. No retry.

## Effect on the controller

Controller 0.6.0 published only within 35 s after a bridge poll, because 1.3.9
dropped anything later. With 1.3.10 it may publish at any time; the bridge adds
at most one read per command. At the controller's limit of 6 commands a day this
is ≤18 extra requests a day (refresh, write, confirmation), within the
controller's 220-a-day request budget and the bridge's 24 refreshes a day. See
the controller PR for the matching change; 0.6.0 itself keeps working with
1.3.10 (poll-aligned, so normally no refresh is needed).

## What the update keeps

- `/data`: credentials, tokens, the authentication guard, the device cache and
  the request ledger (gains a `command_refresh` count, other counts kept);
- every option value, including `commands_enabled` and `command_policy`;
- 30-minute polling; demand refresh stays off;
- MQTT discovery unique IDs, so every entity ID.

## Update steps (after the PR is merged into `main`)

1. **Before updating**, open the add-on Configuration and confirm
   `commands_enabled: false`. If it is still true from T3, set it to false and
   save first, so the update itself cannot carry out a command.
2. **Optional, about 30 seconds:** Settings → System → Backups → Create backup →
   *partial* → only **Thermowatt Smart Boiler**. This is the only way back to
   1.3.9.
3. Settings → Add-ons → Add-on Store → ⋮ → **Check for updates**.
4. Open **Thermowatt Smart Boiler**. It shows **1.3.10**, marked as needing
   attention (`breaking_versions`, never automatic). Click **Update** and wait
   for *Running*.
5. **Log:** `Bridge running; cloud=True, commands=False. Poll interval=1800
   seconds …`, with no `Startup paused` and no auth errors.
6. **Home Assistant:**
   - if the heater is OFF, *Vendor mode* shows **Off** (attribute `Cmd` 8) and
     the water heater shows **off**, no longer Unknown;
   - *Last successful poll* keeps advancing every 30 minutes, and *Cloud
     health* is `ok`;
   - diagnostics attributes show `commands_enabled: false`, `command_policy:
     automation`, `command_status_refreshes_24h: 0`,
     `command_status_refresh_limit_24h: 24` and request category
     `command_refresh: 0`;
   - the same entities with the same IDs, and no new device.
7. The Thermann app is unchanged.

**Fail:** `Startup paused`, auth errors or polling stops. Do not change
`auth_retry_generation` or retry authentication. Restore the step 2 backup or
report the fixed log codes.

## Supervised validation (T3b), a separate approval

The owner is present with the Thermann app open and the heater's power reading
visible. The controller's *Automatic heater control* stays **off** throughout;
commands are published by hand. Stop at the first unexpected result.

The MQTT topic is `P/<serial>/CMD/MODE` (Settings → Devices & services → MQTT →
Configure → Publish a packet). The payload is exactly `off` or `Manual:70`.
**Retain** must be off.

0. **Start:** the heater is in Manual 70 °C, shown in the app and as Vendor mode
   *Manual*. Set `commands_enabled: true` (leave `command_policy: automation`)
   and save. The add-on restarts and polls once.
1. **Stale-status OFF.** Wait until *Status age* is over 120 s (2 minutes after
   the last poll). Publish `off`. Within about a minute:
   - `last_command`: `result: observed_in_status`, `status_refresh: refreshed`;
   - request categories: `command_refresh` +1, `command` +1, `confirmation` +1;
   - Vendor mode **Off** (`Cmd` 8), water heater **off**, the app shows OFF;
   - if the element was heating, power falls by about 3 kW.
   Record the reported `T_SetPoint` (T3 saw 70).
2. **Duplicate.** Within 60 s publish `off` again. Expect
   `already_in_requested_state` and no `command` increase.
3. **Policy.** Publish `Eco`. Expect `refused_by_policy` and no request
   increase. The heater stays OFF.
4. **Stale-status resume.** Wait until *Status age* is over 120 s. Publish
   `Manual:70`. Expect:
   - `observed_in_status`, `status_refresh: refreshed`;
   - Vendor mode **Manual** (`Cmd` 9), target 70, the app shows Manual 70 °C;
   - if the tank is below the thermostat's restart point, power rises by about
     3 kW (a hot tank may not heat, which is not a failure).
5. **Finish:** set `commands_enabled: false` and save, unless the next stage
   (controller supervised trial) has been approved.

**Stop immediately** if:
- any result differs from the above, or a `refused_*`/`dropped_*` code appears
  unexpectedly;
- OFF reports a usable target other than 70 °C;
- the target ever changes from 70 °C;
- the app disagrees with Home Assistant;
- power does not follow the mode as expected;
- any authentication or quota error appears.

Then set `commands_enabled: false`, restore the app setting yourself if needed,
and report the fixed codes. No credentials, tokens or response bodies are
needed in the report.
