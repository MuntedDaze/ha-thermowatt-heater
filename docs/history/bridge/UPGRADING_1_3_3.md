# Upgrading the existing add-on from 1.3.2 to 1.3.3

1.3.3 packages the already-reviewed Vendor mode and unverified-heating changes.
It introduces no further runtime/authentication/control features. PR #2 remains
draft and unmerged; this document is preparation, not approval to install or
enable commands. The running Home Assistant installation was not accessed.

## What the upgrade preserves

| Item | Compatibility |
| --- | --- |
| Add-on identity | Same repository add-on folder and slug `thermowatt_boiler`; no replacement app or new data directory. |
| Credentials/options | Same option names, schema and defaults. Installed email/password, cloud/command flags and `auth_retry_generation` are not rewritten by the bridge. Supervisor continues supplying `/data/options.json`. |
| Tokens | Existing access/refresh tokens remain in `/data/auth_state.json`; startup reuses the saved authorised session instead of forcing password login. Normal token expiry/revocation and the existing refresh policy still apply. |
| Lockout/retry state | Same version-1 guard format/path, consumed generation, account binding, attempt budget and retry deadline. A blocked account stays blocked. An in-flight interrupted attempt becomes blocked, as in 1.3.2; its uncertain tokens are discarded rather than reused. |
| Device identity | Existing device UUID and serial/name metadata in `/data/thermowatt_config.json` are retained. |
| MQTT identity | Existing `thermowatt_<serial>_v314` heater, `thermowatt_<serial>_heating` binary sensor and `tw_<serial>` device IDs/topics remain. Only the already-reviewed Vendor mode sensor is additive. |

For the owner's current `cloud_enabled=true`, `commands_enabled=false` setup,
those values remain true/false after a normal update. New installations still
default both to false. Other deliberately configured values are also preserved;
the upgrade neither silently enables nor forcibly disables an existing setting.
Do not paste the default/example configuration over installed options.

No authentication code, base image, launcher or persistent schema changes are
part of this release-preparation step. No retry-generation increment, credential
re-entry, token deletion, lockout reset or schedule rewrite is required merely
because the version changes.

## Deliberate visible changes

- Vendor mode labels inherited Cmd 17 as Schedule. Native water-heater mode
  remains Unknown for Schedule/Holiday; it is not relabelled Manual or Eco.
- The existing Heating binary sensor is labelled unverified and reports Unknown.
  `result.heating` is JSON null, including when older retained booleans exist.
  Review consumers that previously treated it as confirmed element on/off.
- Raw Cmd/WaterHeaterSts attributes remain diagnostic data, not proof of element
  energisation. Commands and heating optimisations remain unverified/disabled in
  the owner's configuration.

1.3.3 is listed in `breaking_versions` to require attention to these state
semantics rather than silently auto-updating consumers. This does not clear or
alter options/data. [Supervisor documentation](https://contributors.home-assistant.io/apps/how-apps-work/)
states that updates replace the container while retaining its private `/data`.

## Later owner-approved update procedure

After the PR is reviewed, merged and the owner approves installation:

1. Use the existing add-on's normal **Update** action after refreshing repository
   information. Do not uninstall/reinstall, change slug/repository identity or
   delete `/data`. Keep the existing private backup under the owner's normal
   backup policy; it contains credentials and tokens and must not be shared.
2. Leave current credentials, cloud/command flags and retry generation as they
   are. Do not enable commands or clear a lockout as part of updating.
3. Check the displayed add-on version, existing entities and new Vendor mode
   sensor. Unknown Heating is intentional. A rejected/expired cloud session
   continues to follow the existing safeguards, not an upgrade-specific retry.

No part of this procedure was executed on the owner's server. Restoring an old
backup, deleting private storage, changing accounts/generation or reinstalling
can change the retained state; these are not the normal update scenario tested.

## Validation scope

The synthetic fixture in `tests/fixtures/upgrade_1_3_2.json` was generated offline
with the actual 1.3.2 code at commit `dfc3c4e` using local guard transitions, not
live authentication. It covers authorised, blocked, retry and interrupted states.
Tests verify all four cloud/command flag combinations, credentials/options,
tokens, deadlines, generation, metadata and existing discovery IDs.

Native amd64/aarch64 container checks also start replacement 1.3.3 images using
1.3.2-format synthetic `/data`, both authorised and blocked. Cloud and commands
are disabled, test-only HTTP/socket guards remain active, and zero external
requests are required. This exercises container replacement and real filesystem
state, not an actual Supervisor store upgrade. Official Supervisor schema checks
and all existing offline tests remain in CI; review PR #2's final CI results.

Actual owner HA OS update/UI behavior, live token validity and physical heater
control were not tested. No new live test or deployment is authorised here.
