# Progress checkpoint

Last updated: 15 Nov 2026. Update this file at the end of each working session.

## Where the work lives

- Branch: `fable/thermann-energy-dashboard`, cut from the audited baseline `1b29be1` (PR #27).
- Worktree: `C:\Users\jacob\Documents\ChatGPT\ha-thermowatt-heater-fable`. **Not** the shared `ha-thermowatt-heater` directory, which Codex uses on `codex/smart-controller-next`.
- Files owned: `energy_monitoring/**`, `tests/test_energy_monitoring_*.py`, `tests/energy_template_shim.py`, `.github/workflows/energy-monitoring.yml`. Nothing else is touched.
- Local test run (Python 3.11, shared `.test-deps` read-only):
  `PYTHONPATH=../ha-thermowatt-heater/.test-deps python3.11 -m pytest -p no:cacheprovider`

## Done

- Entity map with validation; zero to three CT circuits; smart plugs with an optional parent circuit.
- Generated package: live power split, tariff period and prices, cost and earnings accumulators, peak/off-peak import, self-consumption, untracked load, hot-water attribution, heating-cycle capture, monitoring health.
- Generated dashboard: seven views, built-in cards only, read-only.
- Reference calculations (`calc.py`) and report tool (`report.py`).
- Offline tests: templates rendered and compared with the reference; structure and safety checks.
- CI job running Home Assistant `check_config` on the package, networking disabled.
- README (install, verification checks, limits) and `ENTITY_CONTRACT.md`.

- Final review (15 Nov 2026) against Codex's `codex/smart-controller-next` at `b9620a8`:
  - Contract corrected: the controller's `heater_power` / `heater_energy` map to the raw meter entities, not to `sensor.em_hot_water_power` (the wrapper does not re-report a steady value and hides the sign).
  - Fixed: a missed start after a meter drop-out could pair the next stop with the previous run's start.
  - Circuit readings now accept W or kW and Wh or kWh, as the controller does.
  - All 23 controller and 5 bridge entity IDs in the map exist at `1b29be1` and at `b9620a8`.
- CI on PR #32: all four workflows passed on the first push (owner-verified), including `check_config` on HA 2026.10.4 and 2026.11.1 with 0 and 3 CT circuits.

## Not done / not verified

- Nothing is installed in Home Assistant. No template has run inside a real Home Assistant with live entities.
- The dashboard YAML has not been loaded in a Home Assistant frontend; card options are checked structurally only.
- Smart-plug IDs marked `[unverified]` in the map (server, network cupboard, jrig, garage) are pattern guesses.
- Whether the GoodWe entities go unavailable overnight is unknown (`solar.zero_when_unavailable`).
- No CT meter exists yet, so hot-water sensors are tested with synthetic entity IDs only.

## Next, in order

1. Owner: confirm the `[unverified]` entity IDs and overnight GoodWe behaviour.
2. Owner approval, then install (README steps 1–6) and run checks V1–V7.
3. When the Shelly is chosen and fitted: map the circuits, regenerate, run V8–V10.
4. When Codex exposes expected completion, next poll and poll interval: add the real IDs to the map.
5. Optional: a booted-Home-Assistant smoke test that feeds synthetic states through the package (like `tools/readiness/shadow_ha_smoke.py`).
