# Updating Thermowatt 1.3.10 → 1.3.11, and the supervised validation (T3c)

**Not yet approved. Nothing here has been done.** Merging the PR, installing
the update, enabling commands and the supervised test are four separate owner
approvals.

## Why 1.3.11

T3b (1.3.10, controller 0.6.1 disabled):
- a stale-status `off` triggered one pre-command read (`status_refresh:
  refreshed`, `command_refresh: 1`);
- the POST was accepted and the official app then showed OFF;
- but the bridge reported `not_observed_in_immediate_status`, with no cloud or
  authentication error.

**Root cause.** 1.3.10 made exactly one status read immediately after the POST
(milliseconds later). The cloud had not yet reported the new mode, so that read
showed the old one. The bridge published it as the current status and ended the
command there, with no later check. A delayed cloud update was therefore
indistinguishable from a command that did nothing. The bridge did not record
which mode that read showed, so T3b cannot tell how long the cloud took.

## What a command now does after its POST

| Fresh status read shows | Result | Then |
| --- | --- | --- |
| the requested mode (for `Manual:70`: Manual **at 70 °C**) | `observed_in_status` | done |
| still the previous mode | `awaiting_confirmation` | the next follow-up read |
| neither (e.g. Schedule, Manual 65, an unknown code) | `unexpected_state_after_command` | done; owner checks |
| nothing confirms it by 360 s after the POST | `not_confirmed_within_limit` | done; owner checks |

- **Follow-up reads:** at most two, **60 s** and **300 s** after the POST. A
  background poll in that window counts too, without a duplicate read.
- **The POST is never repeated**, not even after a POST timeout or HTTP error.
  Those may still have reached the heater, so they are observed the same way
  (`awaiting_confirmation` with an `error` code). An explicit cloud rejection
  is final (`rejected_by_cloud`).
- **Failed follow-up reads** (timeout, 5xx) do not decide anything. The next
  follow-up may still confirm, otherwise the deadline ends it. A 401/403/429
  keeps the existing persistent lockout; the deadline still ends the command
  without any request.
- **One uncertain command at a time.** Meanwhile every command, including an
  MQTT redelivery of the same one, is refused with no request and shown in
  `refused_while_pending`. `last_command` keeps the pending record.
- **Restart.** The pending command is saved privately (`command_state.json` in
  the add-on's `/data`, no credentials) before the POST. After a restart it is
  never re-sent; the startup poll or the deadline decides it.
- **Worst case per command:** 5 requests (pre-command read, POST, immediate
  read, two follow-ups). At the controller's 6 commands a day that is ≤30, well
  inside its 220-a-day budget. The 30-minute polling is unchanged.

**New diagnostics (Cloud health attributes):**
- `last_command`: `observed_mode`, `status_reads`, `followups_done`,
  `posted_at`, `confirm_by`;
- `command_confirmation_pending`;
- `command_confirmation_followups_seconds: [60, 300]`;
- `refused_while_pending`.

## What the update keeps

- `/data`: credentials, tokens, the authentication guard, the device cache and
  the request ledger;
- every option, including `commands_enabled: false` and `command_policy:
  automation`;
- the `Cmd` 8 OFF mapping, 70 °C rules, allowlist and refresh limits;
- 30-minute polling, with demand refresh off;
- all entity IDs.

## Update steps (after the PR is merged into `main`)

1. Confirm `commands_enabled: false` (set after T3b).
2. **Optional, about 30 seconds:** a partial backup of only **Thermowatt Smart
   Boiler**. This is the only way back to 1.3.10.
3. Add-on Store → ⋮ → **Check for updates** → open the add-on → it shows
   **1.3.11** → **Update**. Wait for *Running*.
4. **Log:** `Bridge running; cloud=True, commands=False. Poll interval=1800
   seconds …`, with no `Startup paused`, no `command_state_invalid` and no auth
   errors.
5. **Home Assistant (Cloud health attributes):**
   - `command_confirmation_followups_seconds: [60, 300]`;
   - `command_confirmation_pending: false`;
   - `commands_enabled: false`, `command_policy: automation`;
   - polls continue, cloud `ok`, the same entities.
6. The Thermann app is unchanged.

**Fail:** `Startup paused`, auth errors or polling stops. Do not change
`auth_retry_generation`. Restore the step 2 backup or report the fixed codes.

## Supervised validation (T3c), a separate approval

The owner is present, with the app open and the power reading visible.
*Automatic heater control* stays **off**; commands are published by hand
(Settings → Devices & services → MQTT → Configure → Publish a packet; topic
`P/<serial>/CMD/MODE`, **retain off**). Stop at the first unexpected result.

0. **Start** in Manual 70 °C. Set `commands_enabled: true` (policy
   `automation`) and save; the add-on restarts and polls once.
1. **Stale-status OFF.** When *Status age* is over 120 s, publish `off`. Watch
   `last_command.result` for up to **6 minutes**:
   - it should move through `refreshing_status`, `submitted_awaiting_status`,
     possibly `awaiting_confirmation`, and end at **`observed_in_status`**;
   - record `status_reads`, `followups_done` and the time from `posted_at` to
     the result: this is the cloud's actual readback delay;
   - Vendor mode **Off** (`Cmd` 8), water heater **off**, the app OFF;
   - about −3 kW if the element was heating.
2. **While awaiting** (only if step 1 showed `awaiting_confirmation`), publish
   `off` again. Expect `refused_while_pending` with
   `refused_confirmation_pending`, **no** extra request, and `last_command`
   unchanged.
3. **After step 1 has ended**, publish `off` again within 60 s of the last read.
   Expect `already_in_requested_state` and no write.
4. **Resume.** When *Status age* is over 120 s, publish `Manual:70`. Expect the
   same sequence, ending at `observed_in_status`, Manual **70 °C**, the app
   Manual 70, and about +3 kW if the tank is below the thermostat's restart
   point.
5. **Finish:** set `commands_enabled: false` unless the controller trial is
   approved.

**Stop immediately** at:
- `not_confirmed_within_limit`, `unexpected_state_after_command`,
  `rejected_by_cloud` or any unexpected `refused_*` / `dropped_*`;
- a target other than 70 °C;
- the app disagreeing with Home Assistant after the result;
- power not following the mode;
- any authentication or quota error.

Then set `commands_enabled: false`, set the heater as you want it in the app,
and report the fixed codes plus `status_reads`, `followups_done` and the
timings. No credentials, tokens or response bodies are needed.
