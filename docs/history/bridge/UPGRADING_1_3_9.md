# Updating Thermowatt 1.3.8 → 1.3.9 (before T3; commands stay disabled)

**Not yet approved. Nothing here has been done.** The update replaces the bridge
code only:
- credentials, tokens, authentication guard state, request accounting and the
  device cache are kept (`/data` is not touched);
- the 30-minute polling and every existing option value are kept;
- MQTT discovery and entity IDs are unchanged;
- `commands_enabled` stays **false**, so the update sends **no heater command**.

## What 1.3.9 changes

- **`command_policy`**: a new option, default **`automation`**. It accepts only
  `MODE=Manual:70` (heating permitted) and `MODE=off` (parked). Everything else
  is refused before any cloud request, recorded as `refused_by_policy`:
  temperature writes, Eco, Auto/Schedule, plain Manual, Holiday and malformed
  payloads. `legacy` restores the 1.3.8 commands only if you choose it.
- **Guarded `Manual:70`**: sends 70 °C explicitly. It is accepted when the fresh
  status shows 70 °C, or OFF with no usable setpoint. A usable other target,
  OFF included, is refused with no request.
- **While OFF**, a setpoint outside 20–75 °C no longer fails the poll. 1.3.8
  would back off for hours in that case. The status is published with
  `setpoint_valid: false`.
- **Diagnostics** now include `commands_enabled`, `command_policy` and
  `last_command`, the outcome of the latest command as a fixed code with no
  payload text.

Monitoring of every vendor mode, temperature, diagnostic and cloud state is
unchanged.

## Why it must be merged first

The add-on is installed from this repository's `main` branch and built locally
by the Supervisor. 1.3.9 appears as an update **only after PR #12 is merged into
`main`**. That merge needs the owner's explicit approval, because PR #12 changes
heater-command handling.

Do not install the code as a separate "local add-on" instead. It would get a
new slug and empty `/data`, losing the credentials, tokens and guard state.

## Steps, one action at a time

1. **Optional, about 30 seconds: a small add-on backup.** Settings → System →
   Backups → Create backup → *partial* → select only **Thermowatt Smart Boiler**.
   This is the only practical way back to 1.3.8, because the Supervisor cannot
   downgrade from the store. Skip it if you accept that.
2. **Refresh the store.** Settings → Add-ons → Add-on Store → ⋮ → **Check for
   updates**.
3. **Open Thermowatt Smart Boiler.** It shows **1.3.9**, marked as needing
   attention: 1.3.9 is in `breaking_versions`, so it never updates on its own.
   Read the changelog.
4. **Note the current Configuration** without changing it:
   - `cloud_enabled: true`;
   - `commands_enabled: false`;
   - `on_demand_refresh_enabled: false`;
   - 30 minutes polling;
   - `auth_retry_generation` unchanged.
5. **Click Update.** The Supervisor rebuilds the image locally, then restarts the
   add-on. Wait until it shows *Running*.
6. **Check the add-on Log.** Expect `Bridge running; cloud=True, commands=False.
   Poll interval=1800 seconds …`. There should be no `Startup paused` and no auth
   errors.
7. **Check the Configuration again.** Expect the new `command_policy:
   automation`, with `commands_enabled: false` and `on_demand_refresh_enabled:
   false`. Do **not** change anything.
8. **Check Home Assistant:**
   - *Last successful poll* advances about every 30 minutes;
   - *Cloud health* `ok`;
   - its attributes now show `commands_enabled: false`, `command_policy:
     automation`, `last_command: null`;
   - request categories `command: 0`;
   - the same entities with the same IDs, and no new device.
9. **Check the Thermann app** is unchanged.

**Controller 0.6.0** stays disabled. It now sees `commands_enabled: false`
reported by the bridge, which is one more gate that blocks any command.

**Pass:** the bridge polls normally with authentication intact, and commands are
disabled with the automation policy shown.

**Fail:** `Startup paused`, auth errors, or polling stops. Do not retry
authentication or change `auth_retry_generation`. Restore the step 1 add-on
backup, or report the log codes. No credentials or log bodies are needed.

T3 (supervised `off` / `Manual:70` testing) is a separate, later approval; see
`shadow_controller/COMMISSIONING.md` Stage B.
