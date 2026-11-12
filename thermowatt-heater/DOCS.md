# Thermann Hot Water

*Unofficial community software, not a Thermann product. Formerly "Thermowatt Smart Boiler": only the display name changed; the app slug, options, MQTT topics and entity IDs are the same.*

Reads a Thermann / Thermowatt water heater from the MyThermowatt cloud (the API used by the Thermann Control app) and publishes it to Home Assistant over MQTT. Optionally, it accepts two heater commands from the Hot Water Controller.

**Defaults are safe:** cloud access off, commands off, polling every 30 minutes.

## Configuration

```yaml
email: ""
password: ""
cloud_enabled: false
commands_enabled: false
command_policy: automation
poll_interval_minutes: 30
poll_interval_unit: minutes
min_cloud_retry_minutes: 60
on_demand_refresh_enabled: false
auth_retry_generation: 0
```

| Option | Meaning |
| --- | --- |
| `cloud_enabled` | Allows this add-on to use the cloud at all. |
| `commands_enabled` | Allows MQTT heater commands. Leave `false` for read-only use. |
| `command_policy` | `automation` (default) accepts only `MODE=Manual:70` and `MODE=off`, and refuses everything else before any cloud request. `legacy` restores the older, broader command set; only choose it deliberately. |
| `poll_interval_minutes` + `poll_interval_unit` | Background polling: 1–120 minutes, or 60–7200 seconds. 30 minutes is recommended. |
| `min_cloud_retry_minutes` | First wait after an ordinary cloud error, 5–1440 minutes (default 60). Repeated errors double it, up to 24 hours. A success resets it. |
| `on_demand_refresh_enabled` | Optional read-only refresh on `P/<serial>/refresh`, at most one read per 5 minutes. Off by default; the controller does not need it. |
| `auth_retry_generation` | Increase by one to allow **one** new authentication attempt after a lock (see below). 0 starts locked. |

Options are read from `/data/options.json` (`!secret` works). Credentials are never logged or passed on the command line.

## What appears in Home Assistant

- **Water heater:** current reading, target, and mode (`off`, `eco`, `performance` = Manual; Schedule and Holiday show as unknown).
- **Vendor mode sensor:** Manual, Schedule, Eco, Holiday, Off, or Unknown, with the raw `Cmd` and `WaterHeaterSts` as attributes. On the tested heater OFF is `Cmd` 8; `Cmd` 16 is also treated as OFF.
- **Diagnostics:** last successful poll, status age, cloud health, last error, request counts, and command state (`commands_enabled`, `command_policy`, `last_command`).
- **"Heating" binary sensor:** always unknown. The status bit has no published definition. Use the controller's meter-based element state instead.

The reading comes from a sensor near the **bottom** of the tank. It can drop sharply during a shower while the top is still hot, so it is not the temperature of all the water.

## Commands (when enabled)

Under the `automation` policy:
- `Manual:70` is accepted only from OFF. It sends 70 °C explicitly; an OFF target other than 70 that is still usable is refused, never overwritten.
- `off` is accepted only from Manual at 70 °C.
- Anything else, including a change made in the app since the last poll, is refused with no request.
- A command already in place (OFF while OFF) sends nothing.

How a command is carried out:
1. **Fresh status first.** A command needs status no older than 60 s. If it is older, the bridge reads once first, after checking the policy, the command's age (≤ 30 s), the device, authentication, quota and backoff. It allows at most 24 such reads a day.
2. **Sent once.** The command is recorded privately, then sent **once**, never repeated.
3. **Confirmed from the heater's reported state.** The cloud reports changes late (about a minute on the tested heater). If the first read still shows the old mode, the command is *awaiting confirmation*. Two follow-up reads, at 60 s and 300 s, decide it:
   - `observed_in_status`: confirmed;
   - `unexpected_state_after_command`: neither the old nor the requested state;
   - `not_confirmed_within_limit`: after 6 minutes.
4. **One uncertain command at a time.** While one awaits confirmation, every other command is refused.
5. **Restart-safe.** A restart never re-sends a command.

Retained MQTT messages and commands older than 30 seconds are ignored.

## Authentication safety

- **Transient failures** (timeouts, connection errors, HTTP 5xx) get at most three attempts, 60 s and then 300 s apart. The count survives restarts.
- **Rejections lock immediately.** That covers 401, 403, 429, an unrecognised response, or a TLS error. The bridge then idles; it does not exit or loop.
- **Locks are persistent.** Restarting, updating, changing the password or toggling Watchdog does **not** clear a lock.
- **Token expiry:** a read that gets 401 refreshes the token once and repeats the read once. A second 401 within 5 minutes of a refresh locks (`cloud_refresh_cooldown`).
- **Commands are never replayed** after an authentication failure.

### Clearing an authentication lock (owner action)

1. Stop the add-on.
2. Find and fix the cause: account, password, or the vendor's own lock (check with Thermann). Keep `commands_enabled: false`.
3. Set `auth_retry_generation` to a number **larger than any used before** (for example 1 → 2). Start the add-on once.
4. If it locks again, leave it locked and investigate. Do not keep incrementing.

Never delete `/data/auth_state.json`, and do not restore an old backup to "reset" it: it holds the lock, the deadlines and the private tokens. Run only one bridge per account.

## Troubleshooting

| Log code | Meaning | What to do |
| --- | --- | --- |
| `auth_http_401` / `auth_http_403` | Login rejected | Check the account in the Thermann app or with Thermann support, then clear the lock |
| `auth_http_429` | Rate limited | Wait; the local lock stays until you clear it |
| `auth_response_unrecognised` | Unexpected login response | Compatibility problem; don't retry repeatedly |
| `auth_tls_error` | Certificate check failed | Check the system clock and certificates; never disable verification |
| `auth_retry_exhausted` | Three transient failures | Check the network, then clear the lock |
| `interrupted_auth`, `storage_invalid` | Outcome unknown or storage damaged | Repair storage, then clear the lock |
| `cloud_daily_limit`, `cloud_http_429` | Cloud quota reached | Wait for the backoff; don't restart repeatedly |
| `cloud_backoff`, `cloud_timeout`, `cloud_http_5xx` | Ordinary cloud error | Waits automatically (60 min, then doubling) |
| `cloud_success_false`, `cloud_error_nonempty`, `cloud_result_missing`, `cloud_envelope_not_object`, `cloud_invalid_json` | The cloud returned an unusable response | Usually temporary; it retries after the backoff |
| `refused_by_policy` | A command outside the allowlist | Expected; nothing was sent |
| `refused_mode_mismatch`, `refused_target_mismatch` | The heater is not in the state the command expects (often an app change) | Check the app |
| `not_confirmed_within_limit` | Sent once, not confirmed in 6 minutes | Check the app; nothing is repeated |

Logs never contain credentials, tokens or response bodies.

## Recovery

- **Hot water now:** Thermann app → **Manual at 70 °C**. Back to your normal programme: **Schedule**.
- **Stop commands:** set `commands_enabled: false` and restart the add-on.
- **Roll back an update:** restore the partial backup of this add-on taken before updating. That is the only way back to an older version.

Older detailed notes (per-version upgrade guides, diagnostic reviews, deployment evidence) are in [docs/history](https://github.com/MuntedDaze/ha-thermowatt-heater/tree/main/docs/history).
