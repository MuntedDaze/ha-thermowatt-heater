# Review manifest — Thermann Shadow Planner / EMHASS live configuration

Prepared 2026-11-11 (Hobart) for an independent audit. **Synchronisation and
evidence collection only:** no optimisation logic, hot-water setting, EMHASS
behaviour, native Schedule or heater state was changed. Nothing was deployed,
merged or written to Home Assistant. All access to the HA installation was
read-only (Samba `config`, `addon_configs` and `backup` shares).

## 1. Repository state

| Item | Value |
|---|---|
| Repository | `MuntedDaze/ha-thermowatt-heater` (public) |
| Review branch | `codex/review-live-config-2026-11-11` |
| Based on | `bd95f04504fb77ac1e7e45ac64dd7291b9d3999c` = tip of `codex/phase2a-shadow-controller` (draft PR #9) |
| Added on the review branch | this `audit/` directory only (one commit on top of `bd95f04`; its SHA is reported with the push) |
| `main` | not modified; PR #9 not merged |

### Git reconciliation (before creating the branch)

- `git fetch --all --prune` completed for `origin` and `upstream`.
- `codex/phase2a-shadow-controller`: clean working tree, **no untracked files**,
  no stashes, and **0 commits ahead/behind** `origin/codex/phase2a-shadow-controller`.
  Everything up to `bd95f04` was already pushed; there was no uncommitted local
  development work to include.
- One local branch has an unpushed commit: `codex/record-thermann-readonly-success`
  at `c4d2a78` ("Record owner-reported Thermann read-only success and pause
  development", 2026-11-09). It is a documentation-only commit on the old 1.3.2
  line (parent `0563547` from `origin/codex/auth-safety-1.3.2`), touching
  `CHANGELOG.md`, `DEPLOYMENT_READINESS.md`, `README.md`, `SECURITY_REVIEW.md`,
  `thermowatt-heater/CHANGELOG.md` and `thermowatt-heater/DOCS.md`. It is not
  part of the Shadow Planner work and is **not included or pushed**; it was left
  untouched. Its add-on file changes would conflict with the protected v1.3.8
  directory if ever merged, so it needs an owner decision, not silent resolution.
- No conflicts arose. No reset, force-push or merge was performed.

### Local repository files examined

No new, changed or untracked files existed in the working tree. The only files
created are the `audit/` snapshots listed below.

## 2. Snapshots of the running installation

Snapshot time ≈ 2026-11-11 11:40–12:00 Hobart. HA Core **2026.11.1** (from
`/config/.HA_VERSION`).

| File | Represents | Provenance / verification |
|---|---|---|
| `home_assistant/configuration.yaml` | **current** HA `configuration.yaml`: EMHASS `rest_command`s, the two forecast template sensors, recorder exclusions | Byte-identical (after CRLF→LF) to the live file; no secrets in it (`127.0.0.1` is loopback). |
| `home_assistant/automations.yaml` | **current** automations file. It contains exactly one automation: *EMHASS - Update solar and household forecasts* (the 30-minute forecast automation with the corrected validation logic) | Byte-identical to the live file. File modified 2026-11-11 11:24. |
| `emhass/config.json` | **current** EMHASS add-on `config.json` (panels/inverter, GoodWe entities, prices, forecast methods) | Byte-identical to the live `addon_configs/5b918bf2_emhass/config.json` (modified 2026-11-11 10:15; `config.json.backup` is identical). It contains no credentials or coordinates. |
| `thermann_shadow/config_entry.json` | **current** saved Shadow Planner config entry: entity mappings (`data`, `options.sources`) and every saved option | Extracted from `.storage/core.config_entries` (only this entry; `entry_id` replaced by a placeholder). |
| `thermann_shadow/live_vs_repo_defaults.json` | Differences between live options and repo defaults | Computed against `config.py` at `bd95f04`; the live options also parse and validate with that code. |
| `thermann_shadow/installed_component_match.json` | Which repo commit is installed | All 22 installed files hash-identical to `bd95f04` (and to `9f09a31`/`4dbf84e`, between which the component did not change). |
| `home_assistant/related_metadata.json` | Deployed versions, the `input_datetime` helper, Forecast.Solar planes (non-sensitive), selected entity registry summary, last *saved* states of the forecast inputs, dashboard registration | Selected records only; see the notes inside each section. |
| `home_assistant/emhass_automation_trace_PREVIOUS_VERSION.json` | The only saved automation trace | **Not the current automation version** (it uses `wait_template`, a different description and no freshness re-check). Kept as history and clearly labelled. |
| Hot Water dashboard | The stored `lovelace.hot_water` dashboard | Parsed config is **exactly equal** to `shadow_controller/dashboard.yaml` at `bd95f04`, so the repo file is the snapshot (not duplicated). |

### Deployed versions (verifiable)

| Component | Version | Source |
|---|---|---|
| Home Assistant Core | 2026.11.1 | `.HA_VERSION` and backup metadata |
| Supervisor | 2026.10.5 | latest automatic backup metadata (2026-11-11 05:06) |
| Thermowatt Smart Boiler add-on | 1.3.8 | backup metadata |
| EMHASS add-on | v0.18.8 | backup metadata |
| Mosquitto broker / Samba | 7.1.3 / 12.10.0 | backup metadata |
| Thermann Shadow Planner (custom) | 0.3.0, files = `bd95f04` | file hashes |

Add-on versions come from the `backup.json` metadata of the 05:06 automatic
backup (no backup contents extracted); an add-on updated after 05:06 would not
be reflected.

## 3. Differences between live configuration and repository

**Shadow Planner options vs `config.py` defaults (`bd95f04`):** only
- `forecast_enabled`: **true** (default false);
- `native_clock_check_date`: `2026-11-11` (default blank; `native_schedule_clock_verified` remains false);
- `sources.forecast_pv` = `sensor.hot_water_pv_forecast_input`, `sources.forecast_load` = `sensor.hot_water_load_forecast_input` (defaults blank).

Every other option (targets, times, tariff rates/periods/clock, cycle timings,
switching benefit, headroom, forecast uncertainty/margins/age) equals the repo
default. No `restore_backup` is stored. Entry `data` equals `DEFAULT_SOURCES`.

**Installed component and dashboard:** identical to `bd95f04` / `dashboard.yaml`.

**Live HA forecast wiring vs the examples in `shadow_controller/FORECAST_SETUP.md`:**
- Template sensors use the documented names/unique IDs, but `forecast_generated_at`
  is rendered with `timestamp_local(default='')` (the saved value was
  `2026-11-11T11:30:04+11:00`), `state` uses `| float(0)`, `device_class: power`
  is added, and availability requires `is_number(...)` plus a non-empty list.
- The automation runs **`dayahead-optim` every 30 minutes** (the guide suggested
  MPC for frequent runs), requires HTTP **200** from both REST commands (guide: `< 300`),
  then polls every 2 s (max 15 tries) and re-checks that both EMHASS sensors are
  numeric, have >10 forecast items and were reported **after the run started**,
  before stamping `input_datetime.emhass_forecast_generated` with local `now()`.
  `mode: single`.
- Forecast.Solar is configured (two planes) but is **not** mapped into the planner.

**EMHASS configuration facts relevant to the audit (recorded, not changed):**
- PV: two strings, `modules_per_string` [10, 5] × `pv_module_model` [440, 440],
  `surface_azimuth` [90, 0], `surface_tilt` [22.5, 22.5]; inverter 5000 W
  (`inverter_ac_output_max` 5000), `maximum_power_to_grid` 5000,
  `maximum_power_from_grid` 9000. Forecast.Solar uses the same split (4400 W at
  90°, 2200 W at 0°) but **25°** tilt.
- Weather: `open-meteo`; load forecast: `naive` on
  `sensor.goodwe_inverter_house_consumption` (`sensor_power_load_no_var_loads`),
  with no deferrable loads (`number_of_deferrable_loads` 0). That house-consumption
  sensor can include native heater runs.
- Prices: peak 0.361878, off-peak 0.1702, export 0.09276 (constant); peak periods
  07:00–10:00 and 16:00–21:00 with `tariff_schedule_time_zone` `Etc/GMT-10`
  (POSIX sign: UTC+10, fixed AEST). These match the planner's Aurora 93 defaults.
- `optimization_time_step` 30, `publish_horizon_attributes` true, `costfun` profit,
  battery disabled.
- Last saved forecast values (11:30 Hobart): PV 3425 W and load **4484 W** for the
  current step; load 5025 W at 12:00.

## 4. Not included, not verifiable, or deliberately excluded

- **Not read:** `secrets.yaml`, `configuration.yaml.backup` (265 bytes, dated
  2026-11-08, an older file, not current), `home-assistant_v2.db`, logs,
  `.cloud`, auth/person/mobile-app data.
- **Not copied:** any whole `.storage` file; other integrations' config entries
  (GoodWe contains the inverter's network address; Forecast.Solar contains
  location and an API key: only the non-sensitive plane options are included).
- **Not accessible via the shares:** Thermowatt add-on options (Supervisor-held;
  include Thermann credentials, so they must not be published anyway) and EMHASS
  add-on Supervisor options (e.g. port mapping). The repo defaults for the add-on
  are in `thermowatt-heater/config.yaml`; the live values were not verified.
- **No live state read:** no HA API token was used, so current values of the
  Shadow Planner sensors (decision, recommendation, controller diagnostics,
  warnings) and of `sensor.p_pv_forecast`/`sensor.p_load_forecast` are not
  included. Only the last *saved* states (restore_state, 11:39) exist for the
  forecast inputs and the helper.
- **Current automation execution:** no saved trace of the corrected version
  exists. The 11:30:04 stamp falls after the file was modified (11:24), which
  suggests, but does not prove, that the corrected version ran successfully.
- **Dashboard rendering** on the owner's devices was not observed.
- No location, IP address, account identifier, token or password is included.
