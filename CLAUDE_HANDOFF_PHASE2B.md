# Claude handoff — Thermann Phase 2B WIP

The owner has run out of Codex usage and explicitly requested handoff to Claude.
Continue the existing work; do not restart the optimiser from scratch. This is
an implementation checkpoint, **not a release-readiness claim**.

## Repository / non-negotiable boundaries

- Workspace: `C:\Users\jacob\Documents\ChatGPT\ha-thermowatt-heater`.
- Origin: `https://github.com/MuntedDaze/ha-thermowatt-heater.git`.
- Branch: `codex/phase2a-shadow-controller`; existing draft PR #9.
- Last fully CI-validated pre-Phase-2B commit: `863ee65fbfa199eecdc4ea89d5fed73d1cde98f0`.
  That fixed hub discovery and `sources: dict(self.sources)`, with 636 tests and
  actual HA WebSocket/Recorder serialization tests. Preserve those fixes.
- Read `AGENTS.md`. Later owner directions explicitly require PR #9 remain
  draft/unmerged. NO deployment, owner HA access, live Thermann API/authentication,
  heater commands, native Schedule/T-Comfort changes or authentication resets.
- The whole `thermowatt-heater/` directory MUST remain byte-for-byte equal to
  current main v1.3.8. Do not bump the add-on. Only the separate shadow component
  has a candidate version bump to **0.3.0**.
- No new paid services or significant dependencies. EMHASS is optional. Native
  local settings controls are allowed; no services may target the heater.

## Full request to read

Owner's pasted Phase 2B brief is at:
`C:\Users\jacob\.codex\attachments\a45e29c7-eda9-4b0d-8e6c-528d25c919a4\Pasted text.txt`.

Subsequent owner additions (part of the same task):

1. Stateful economic cycle simulation: 10 min sustained advantage before optional
   start, 20 min sustained disadvantage before optional stop, 30 min minimum
   intended cycle, 30 min optional gap. Recompute costs, not a fixed surplus stop.
   Comfort overrides ordinary dwell; real native protections/owner intervention
   take priority. Test clouds 2/5/10/20/30/60 minutes, tariffs and deadlines.
2. Dedicated Settings dashboard view: practical native number/time/select/toggle
   controls; CURRENT, RECOMMENDED and ORIGINAL defaults + plain explanation for
   every setting, combining identical defaults. Groups Comfort, Solar &
   Forecasting, Heating Cycles, Advanced. Confirmed restore-recommended function.
   One persistent authoritative config store shared with Configure. Local saves
   recalculate without heater restart, Schedule edits or Thermann cloud calls.
3. Recommended economic switching benefit **AUD 0.10 per proposed decision**,
   experimental. Solar headroom 0.3 kW; morning 40°C at 07:00; afternoon 70°C,
   30 min allowance. Preserve fixed-AEST Aurora 93 and independent comfort times.
4. No merge/deployment. Deliver functioning shadow planning, forecasts, dashboard,
   thorough tests, scenario/cost/cycle results and safe update instructions.

## Implemented but not yet independently qualified

- Existing thermal/fallback engine retained. `model.py` adds validated cycle/
  forecast preferences and editable morning/nominal afternoon times. Slot ranking
  now uses economic unit cost instead of preferring all full-solar slots.
- `economics.py`: full 3 kW continuous-cycle quote now versus feasible later
  windows; minute tariff boundaries, forecast boundaries, import + foregone
  feed-in cost, bounded current-export assumption, finite fallback reservation.
- `forecast.py`: read-only state adapters for standard EMHASS `forecasts` lists
  and a buffered Forecast.Solar `watts` dictionary. Both PV AND house-load series
  require explicit W/kW and `forecast_generated_at` (offset-aware actual
  generation/update, not a publish timestamp). Default disabled. Bounds 48 h/
  576 net intervals. PV −25%, load +25%, extra 0.3 kW demand; fresh actual PV can
  down-correct, never up-correct predictions. Invalid forecasts discard to fallback.
- `cycles.py`: session-local ideal-energy counterfactual state, economic holds,
  dwell/gap, comfort priority, stop overrides for mocked future qualified inputs,
  simulated costs/counts/suppressed switching episodes. No physical heater-state
  inference; simulated load never changes measured HK1000 values. A pure helper
  demonstrates de-embedding ONLY separately verified element power. New observed
  depletion resets a completed scenario; warmer observations cap remaining energy.
- `runtime.py`: local forecasts + cycle simulation, human decision explanation,
  extra sensors/diagnostics. Original mappingproxy copy retained. Sources and
  credentials are never sent anywhere. Actual native mode/target intervention
  continues to gate/latch planning.
- `settings.py`: shared catalogue of explanations, ranges, groups and defaults.
  Native `number/time/select/switch/text/button` modules write config-entry options
  (one authority). Cross-field validation is atomic. Options listener now applies
  locally rather than unloading/reloading on every preference save. Mapping
  changes reset freshness; changed preferences reset the session simulation.
- Common Aurora peak times, prices/weekend flag have native controls. Legacy
  arbitrary weekly JSON selects custom profile automatically. Advanced native
  reference/custom-period JSON remains in Configure, NOT long TextEntity state
  (HA state has a 255-character limit). Date reference uses TextEntity.
- Restore button has dashboard confirmation; restores preference/Aurora defaults,
  preserving mappings, meter flags/sign and native reference settings. Review
  whether confirmation is sufficient: direct button press outside that card does
  not itself display a confirmation. It never operates the heater.
- Native-card dashboard: large temperature/recommendation, power/history/costs,
  dedicated Settings and Diagnostics. Generated by `tools/build_shadow_dashboard.py`
  from catalogue; it also generates EN labels. UI has not been visually reviewed
  in real HA and may need polish. Original/recommended values currently match;
  a future release changing recommendations must retain true original defaults.
- Added `test_shadow_phase2b.py`, `test_shadow_phase2b_scenarios.py`; retained old
  bridge regressions. Expanded actual HA smoke to cover all settings entities,
  native writes/validation/restore, serialization and reload/identity persistence.
- Added `tools/replay_shadow_cycles.py`, reproducible JSON/Markdown results,
  `PHASE2B.md`, `UPGRADING_0_3_0.md` and changelog entries. README historical 0.2
  section is explicitly marked obsolete and needs final consolidation.

## Evidence / important economic interpretation

Confirmed rates: peak 0.361878, off-peak 0.170200, export 0.092760 AUD/kWh.
Weekday peaks 07–10 & 16–21 fixed AEST; weekends off-peak. Hobart DST automatic.
One hour with 2 kW solar + 1 kW off-peak import costs AUD 0.355720, versus
AUD 0.510600 all-grid. Peak mixed cost can exceed all-grid off-peak later.

Start qualification compares solar advantage against a feasible grid alternative;
it also waits if a later forecast is cheaper by the switching threshold. Stop
qualification compares continuing against a feasible later cycle, not just surplus.
Default $0.10 may suppress optional starts when only 15 minutes of current export
can safely be projected. Do not silently lower the owner's recommended threshold
or extrapolate current surplus for a whole day to force activity.

Synthetic report: 18 cases (six cloud durations × off-peak/peak-change/near-deadline).
Default policy has 1–2 cycles versus 2–3 instantaneous-benchmark cycles, avoiding
0–4 switching events, at roughly $0.008–$0.269 extra model cost. Equal 6 kWh is
served in every saved case; no model shortfall. This is a deliberate stability/
cost trade-off, NOT guaranteed financial savings or physical performance. The
benchmark has perfect synthetic cloud-duration knowledge; real failed-forecast
fallback is tested separately. All values must be reproducible after corrections.

## Validation status and required next work

At handoff, local Ruff lint/format, strict existing model/helper mypy and compileall
pass. Focused Phase 2B/model/owner tests and the scenario tests have passed.
Final full-suite status is recorded below by the handing-off agent. Expanded
real HA / native-container / Supervisor CI is NOT yet qualified for Phase 2B.

Handoff local check notes: 706 tests are collected (636 baseline + 70 added).
The first full run passed 705 and found one documentation/packaging invariant:
root and add-on changelogs must stay byte-identical. Removed the root shadow-only
entry rather than changing the protected add-on; the separate shadow changelog
retains 0.3.0 release notes. All 12 packaging tests then passed and both protected
paths match main. A clean full rerun follows this correction; consult its final
status below / the PR validation note. Do not loosen that packaging assertion.

**Final handoff rerun: all 706 tests PASS (exit 0).** Ruff lint/format, both
existing strict mypy targets, compileall and `git diff --check` pass locally.
Bridge directory and root/add-on changelog bytes are unchanged versus main.
Remote CI on this WIP checkpoint still needs review; do not equate local tests
with actual HA, native-container or Supervisor validation.

1. Inspect final CI on the WIP head. Fix genuine failures; do not report HA/native
   checks passed until the final head is green. Native preferences are new HA
   platforms and MUST be tested on actual HA Core 2026.10.4/2026.11.1.
2. Review economics/cycle state carefully, especially energy progress versus
   fresh observed temperatures, new goals, stale intervals, tariff changes,
   minimum dwell + grace interactions and interruption/restart behaviour.
3. Complete practical forecast setup examples. EMHASS standard attributes are
   source-verified, but actual owner mappings and true generation timestamp are
   unknown. Do NOT invent a run-completion event or stamp each republish as new.
   Forecast.Solar cached action is documented; owner-buffer template still needs
   implementation/validation. Forecast collection must remain separate from bridge.
4. Extend actual HA smoke to include forecast-present/invalid paths and validate
   dashboard entity references and Jinja rendering. Current smoke exercises settings
   but has not yet been run on the new version at handoff. Confirm every original
   sensor unique ID, existing saved options, custom tariffs and new controls.
5. Audit dashboard mobile usability/default explanations. Test all meaningful
   settings/forms, invalid combinations, atomic saves, restore and restart. Ensure
   all current/recommended/original defaults are truthful, including advanced
   reference fields and custom periods. Preserve one options authority.
6. Consolidate outdated README 0.2 policy sections; finish release notes and
   installation instructions; do not claim actual owner UI or real-data forecast
   accuracy was tested. Version 0.3.0 is a candidate only.
7. Run every applicable workflow at final head, update existing PR #9 description
   to Phase 2B and include final validation/limitations. Leave draft/unmerged.
   No live HA or cloud activity, no heater commands or automatic deployment.

## Commands / environment

PowerShell uses `C:\Users\jacob\.local\bin\python3.11.exe` (plain `python` is a
broken Windows Store alias). Existing local test dependencies are in `.test-deps`:

```powershell
$env:PYTHONPATH = "$PWD\.test-deps"
& C:\Users\jacob\.local\bin\python3.11.exe -m pytest --basetemp=.pytest_cache/claude-phase2b
& C:\Users\jacob\.local\bin\python3.11.exe -m ruff check .
& C:\Users\jacob\.local\bin\python3.11.exe -m ruff format --check .
& C:\Users\jacob\.local\bin\python3.11.exe -m mypy --strict --follow-imports=skip custom_components/thermann_shadow/model.py
& C:\Users\jacob\.local\bin\python3.11.exe -m mypy --strict thermowatt-heater/thermowatt_read_only.py
& C:\Users\jacob\.local\bin\python3.11.exe -m compileall -q thermowatt-heater custom_components tests tools/readiness
& C:\Users\jacob\.local\bin\python3.11.exe tools/build_shadow_dashboard.py
& C:\Users\jacob\.local\bin\python3.11.exe tools/replay_shadow_cycles.py
git diff --exit-code origin/main -- thermowatt-heater
```

Inspect `.github/workflows/tests.yml`, `deployment-readiness.yml`, and
`shadow-controller.yml`. They run Python 3.12/3.13/3.14, Ruff/mypy/compile/Bash,
native amd64/aarch64 images with isolated MQTT/lifecycle/upgrade tests, Supervisor
2026.10.5/2026.11.0 and real isolated HA Core smoke. Docker/Bash aren't available
locally here; CI is necessary. Network is disabled inside smoke containers.

## Owner/system context

Thermann 315 L / 3 kW; bottom sensor, approximately 8°C hysteresis. Physical
energisation and API On/resume/retention remain unqualified. Native Schedule
weekdays approximately 04–08 & 11–17, weekends 06–22, target 70°C; T-Comfort 10°C
is not a practical comfort reserve. App power Off has documented antibacterial
support while powered, but this is NOT a verified cloud-command/fallback contract.

Default source mappings are in `config.py`: water_heater.home_boiler_home;
sensor.home_boiler_home_vendor_mode; sensor.home_last_successful_poll;
sensor.home_cloud_health; sensor.home_cloud_request_attempts_local_lifetime;
GoodWe PV/house/meter active power. Positive meter active power means export,
owner-confirmed in Phase 2A. Native heating may already affect net grid; do not
add 3 kW solely because a hypothetical cycle is active. Request counter is local
lifetime attempts, not vendor quota; status→refresh→replay can be three attempts.
