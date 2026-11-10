# Thermann Shadow Planner

## 0.3.0 — Phase 2B shadow-only review candidate

- Add optional published EMHASS PV/house-load and buffered Forecast.Solar watts
  adapters; require actual generation provenance, explicit W/kW and bounded data.
  Apply conservative PV/load uncertainty and downward measured-PV correction.
- Compare continuous full-power cycles and partial solar against imported energy
  plus foregone feed-in revenue. Preserve independent full off-peak reservation.
- Add stateful ideal-energy simulation: 10-minute start hold, 20-minute economic
  loss grace, 30-minute optional run/gap, experimental AUD 0.10 switching benefit.
  Comfort, missing data and owner/qualified stop overrides take precedence.
- Native number/time/select/toggle controls use the same config-entry options as
  Configure. Save/recalculate locally; confirmed dashboard restore preserves
  mappings, meter verification/direction and native references. Existing saved
  prices, targets, custom periods and entity IDs are retained.
- Rework native-card Hot Water, Settings and Diagnostics dashboard. Expose
  recommendations, forecast age, whole-cycle costs and explicitly simulated
  cycle counts; no manufactured physical heating/power/energy measurements.
- Add offline forecast/error/upgrade/seasonal/cloud-interruption regressions,
  real HA preference/serialization/restart checks and reproducible cycle reports.
  Keep the complete Thermowatt 1.3.8 directory unchanged; no executor or services
  target the heater, native Schedule/T-Comfort, MQTT or cloud.

## 0.2.0 — confirmed-owner Phase 2A candidate

- Fix Add Integration discovery by classifying the integration as a hub. Copy
  immutable source mappings before exposing diagnostic attributes. Test actual
  WebSocket state/event serialization and Recorder attribute/SQLite storage paths
  on isolated Home Assistant Core, including a mappingproxy negative control.

- Documentation/source review clarifies manufacturer app On/Off hygiene support,
  missing API resume/retention evidence, outages, bounded future cycles and shadow
  installation. Add mocked source-contract tests; no runtime/version change.

- Continue the existing planner/PR; retain the read-only boundary and all bridge
  files at v1.3.8. No deployment or automatic merge.
- Use confirmed Aurora 93 prices and fixed AEST periods, verified export-positive
  meter defaults, editable morning 40°C threshold and afternoon 70°C target.
- Prefer sustained net-export opportunities and latest suitable off-peak backup;
  reserve full backup independently of optional forecasts. One-minute LOCAL
  sampling adds no cloud requests; require a ten-minute export hold by default.
- Add current tariff/price, targets, source, latest-start and device-clock reminders;
  distinguish summer peak deadlines from nominal comfort and weekend goals.
- Update control/recovery design for accepted manual outage recovery, document the
  missing verified stop/resume contract and unestablished factory-reset procedure.
- Extend offline scenarios, HA settings/reload tests and all bridge regressions.

## 0.1.0 — Phase 2A owner-review candidate

- Separate Home Assistant sensor integration with editable entity mappings and
  settings, owner-reported defaults, local five-minute evaluation and a built-in
  card dashboard. No EMHASS/runtime dependencies beyond Home Assistant.
- Hardcoded shadow-only capability: no services, heater controls, MQTT writes,
  network clients, refresh triggers, lockout resets or native schedule changes.
- Explicit measured/estimated/unverified separation; fixed safe decision codes,
  fresh post-restart inputs, cloud-health gates and native-intervention review.
- Provisional export-positive HK1000 sign remains unvalidated by default. Actual
  tariff/DST/weekend settings require confirmation; no published price assumed.
- Uniform 315 L / 3 kW scenarios, deadline shortfalls, net-export opportunities,
  cheap tariff windows and foregone export costs; no inferred usable reserve,
  energy measurement, hygiene status or confirmed element energisation.
- Display observed local request growth; include the 3-attempt refresh/replay
  pattern in illustrative usage estimates, without inventing quota/reset times.
- Offline scenario tests and isolated real HA Core config-flow/lifecycle checks.
  Thermowatt add-on stays 1.3.8 with all bridge files and protections unchanged.
