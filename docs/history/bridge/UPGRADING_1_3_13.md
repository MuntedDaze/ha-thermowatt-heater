# Upgrading the app to 1.3.13

1.3.13 needs owner approval before it is merged or installed, because it
changes authentication timing (proactive token refresh) and the heater
command set. It is a manual update (`breaking_versions`).

## What is preserved

| Item | After the upgrade |
| --- | --- |
| Options | Unchanged: same keys, defaults and schema. `cloud_enabled`, `commands_enabled`, `command_policy`, `on_demand_refresh_enabled` and `auth_retry_generation` keep their configured values. |
| Credentials and tokens | `/data/auth_state.json` keeps the same format and content. The saved authorised session is reused; no password login. |
| Authentication guard | Same modes, attempts, retry delays, 5-minute refresh cooldown and locks. |
| Command state | `/data/command_state.json` keeps version 1. A command pending at upgrade is still never re-sent; the next reads decide it. |
| Request accounting | Same file and categories. |
| MQTT | Same topics, discovery payloads and entity IDs. |

## What changes

- **Commands:** six `<target>@<prior>` transitions are accepted in addition to
  the 1.3.11 `Manual:70` and `off`.
- **Confirmation:** the first status read is now 60 s after the POST, not
  immediately after it. The heater stays available, showing its last
  confirmed status, while the result is `submitted_awaiting_status`.
- **Polling:** clock-aligned (:00 and :30). After the upgrade restart there
  is one read, then polls join the clock slots.
- **Tokens:** a token at least 20 minutes old is refreshed before a request.
  After the restart its age is taken from the guard's saved cooldown, or the
  first request refreshes once.

## Checks after installing (read-only)

1. The log shows the session reused, with no `password_login`.
2. Diagnostics show `cloud_health: ok`, and the guard is `authorized`.
3. The next polls arrive at :00 and :30, each as `token_refresh` + `status`
   (2 requests), not 401 + refresh + status.
4. No command is sent until the supervised tests in
   `shadow_controller/COMMISSIONING_SIMPLIFIED.md`.

## Rollback

Reinstall 1.3.12 (or 1.3.11). Both read the same `/data` files. A 1.3.12
bridge refuses the six new payloads with `refused_by_policy`, so roll back
the controller first, or turn automatic control off.
