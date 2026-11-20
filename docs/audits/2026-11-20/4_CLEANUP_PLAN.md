# Cleanup plan (proposed; nothing implemented)

Goal: one current policy, one specification, an active settings list that is
exactly what the controller uses, and zero loss of stored data. Every step
below waits for the owner's answers in `3_OWNER_DECISIONS.md`.

## Release structure

| PR | Content | Behaviour change? | AGENTS.md class |
|---|---|---|---|
| **A. Docs** | `docs/OPERATING_POLICY.md`; move phase folders to `docs/history/`; fix README/COMMISSIONING/SETTINGS_AUDIT/DASHBOARD_CONTRACT/THERMAL_MODEL; supersede morning requirements | None | Auto-merge scope (docs only) — still held for owner OK per this brief |
| **B. Controller 0.18.0 — inert-settings retirement** | Sections 1–4 below, Decision 3 | None to heating or commands; removes the 10 legacy/developer setting **entities** | Approval: entity removal, validation change |
| **C. Controller 0.18.x — owner choices** | Decision 1 (warning), Decision 2 (Smart only) | Yes | Approval required |
| **D. Bridge 1.5.0 (later)** | Decision 4 | Command-path | Approval required; after live upgrade |

B and C can be one PR if the owner prefers; C must not be merged without the
answers.

## 1. Code that can be deleted (PR B)

- `comfort.morning_availability` (hard-coded 45 @ 06:00 / 42 @ 07:00) and its test.
- From `config.parse_options`: validation of all 32 inert retired keys, including the cross-field rules `morning_preferred_below_minimum`, `morning_times_order`, `afternoon_time_invalid`, `rest_longer_than_latency_reserve`, `native_reference_invalid`, `native_clock_date_invalid`, and the `parse_native` call. Matching `REJECTION_MESSAGES` entries.
- From `model.Settings` / `validate_settings`: the retired fields and ranges (`target_c`, morning/shower/evening times, planner tuning, native references). Keep `export_headroom_kw` until it becomes a constant.
- `native.py` (only validates a retired key).
- `ControllerConfig.bridge_commands_qualified`, `three_state_qualified`, `published_forecasts_enabled` and their dead branches in `missing_commissioning`/`gates` (requires-four-states is permanent).
- `PollingShadow` and the three `adaptive_poll*`/shadow settings (diagnostic only; the report section becomes "not available").
- Stale docstrings (`controller.py` header, `executor.py` header) and the `forecast_unavailable` alert text.
- With Decision 2: `adaptive.make_plan`, `adaptive.event_plan`, the `existing` branch in `Executor` poll planning, `adaptive_polling_enabled`, `event_aware_polling_enabled`, `owner_change_check_minutes`.

Expected size (estimate): several hundred lines of production code; 7 setting
entities fewer (10 with Decision 2); visible settings drop from 66 to 59 (56
with Decision 2).

## 2. Settings retired or removed from the UI

| Group | Action |
|---|---|
| 32 inert Retired keys | Stop validating and reading. Keep in the catalogue's `RETIRED` set purely as a list of tolerated stored keys; no entity (already none) |
| `export_headroom_kw` | Decision 3: constant `SOLAR_START_HEADROOM_KW = 0.3`; the stored key joins the tolerated list. Equivalence test proves 3.3 kW unchanged |
| `controller_three_state_qualified`, `weekend_qualify_minutes`, `weekend_sunset_kw`, `weekend_sunset_minutes`, 3 polling-shadow keys | Retire → entities removed by the existing registry clean-up. **Owner check first:** no dashboard/automation uses them (the shipped dashboards do not) |
| `adaptive_polling_enabled`, `event_aware_polling_enabled`, `owner_change_check_minutes` | Retire only with Decision 2 |
| Legacy page | Deleted when empty; Advanced menu loses one item |
| `learned_planning_enabled`, `learning_hardware_qualified` | Keep (off); move to the Commissioning page's end with "not yet qualified" wording — no removal |

## 3. Compatibility logic that must remain

- `DEFAULT_OPTIONS` merge on load (`{**DEFAULT_OPTIONS, **options}`): unknown/retired stored keys must pass through untouched on every save, Restore and Undo. Today Restore resets non-preserved retired keys to defaults; change it to **preserve** all tolerated retired keys verbatim, so a rollback sees exactly the owner's saved values.
- Config-entry migrations 1.1→1.5 stay (an old backup may still be restored). The 1.1→1.2 step may keep moving 40→42 — it is harmless — or skip it; either way it touches only a stored, unread key.
- `naming.RETIRED_SENSORS` and `_remove_retired_entities` stay (old entities still exist on some installs).
- Entity IDs of every remaining entity, including `sensor.thermann_shadow_morning_availability` (friendly name → "Low hot water before peak").
- Controller store format: the persisted holiday/override/weekend-latch/intent/history fields are unchanged; the `guest_target_c = 70` reader for pre-0.16 overrides is the one exception: such an override expired within 12 hours of being set, so the reader can go in PR B (a missing field then defaults to 62).
- Bridge: credentials, tokens, `auth_retry_generation`, guard/journal files, MQTT topics and discovery IDs untouched. PR B/C do not change the bridge at all.
- Frozen readiness fixtures `tools/readiness/fixtures/thermann_shadow_0_*` stay (upgrade tests).

## 4. Configuration migration

- Entry minor version 5 → **6**, major stays 1 (0.17.1 rollback still loads).
- Migration does **not** delete keys. It only (a) records `retired_options_preserved: true` for diagnostics, and (b) with Decision 2, sets controller `polling_mode = smart` if it is `existing`, logging old → new.
- Rollback check: 0.17.1 loading a 1.6 entry sees every key it validates, with the owner's own values (because Restore no longer rewrites them). A fresh 0.18 entry rolled back to 0.17.1 gets defaults, which pass 0.17.1 validation (test this with the frozen fixture approach).
- Deleting stored keys is **not** proposed. Their cost is a few hundred bytes; deleting them would only make a rollback restore defaults instead of the owner's values.

## 5. Tests requiring revision

| Test file | Change |
|---|---|
| `test_settings_cleanup_0_17_1.py` (12 refs) | Legacy page contents, `SAFE_WHILE_ACTIVE` weekend keys, catalogue counts |
| `test_estimator_and_settings.py:87–88, 178–183` | Morning default/describe assertions → "tolerated retired key, preserved verbatim"; migration assertions keep or drop with §3 choice |
| `test_forecast_and_settings_review.py:179+` | `ORIGINAL_DEFAULTS` pins for retired keys → drop pins for keys no longer described |
| `test_existing_installation_upgrade.py` | Remove `morning_availability` helper use |
| `test_event_aware_polling.py`, `test_polling_shadow.py`, `test_poll_interval.py` | Only with Decision 2 / shadow removal |
| `test_cloud_and_commands.py`, `test_command_refresh_1_3_10.py`, `test_controller_0_9_0.py`, `test_integration_0_9_0.py` | `three_state_qualified`/`bridge_commands_qualified` config arguments |
| Weekend tests | `weekend_qualify`/`sunset` constructor arguments |

New regression tests:

1. A saved retired value that 0.17.1 would reject (e.g. `morning_hard_time` before `morning_preferred_time`) no longer blocks saving an active setting.
2. Retired keys survive save, Restore and Undo byte-for-byte.
3. **D2 guard:** across a simulated weekday 21:00 → 10:00 with the probe falling to 30 °C, the policy never selects 62 or 70 without qualified solar and raises no morning alarm (except the D1 outcome).
4. Boost start threshold remains 3.3 kW (constant equals old setting).
5. Entity-ID snapshot of all remaining entities unchanged.
6. Migration 5 → 6 idempotent; 0.17.1-format options load and validate.
7. (D1) pre-peak warning only before the evening peak.

Plus the full existing suite and CI (`tests.yml`, `shadow-controller.yml`,
`configuration-frontend.yml`, `deployment-readiness.yml`, `energy-monitoring.yml`;
pytest, Ruff, compileall, Python 3.12–3.14, native images, Supervisor schema).

## 6. Documentation corrections (PR A)

- New `docs/OPERATING_POLICY.md` (structure in `3_OWNER_DECISIONS.md`), dated, explicitly superseding the morning requirements.
- `README.md`: current versions (0.17.1 / 1.4.1), link to the policy, remove draft-PR status text.
- `shadow_controller/COMMISSIONING.md`: delete morning goals (lines 37, 65) or mark the file historical (it describes the 0.6/0.7 process; `COMMISSIONING_SIMPLIFIED.md` is current).
- `SETTINGS_AUDIT.md`, `DASHBOARD_CONTRACT.md`, `THERMAL_MODEL.md`, `SIMPLIFIED_STRATEGY.md`, `UPGRADE_0_6_2_TO_0_7_0.md` → `docs/history/controller/`.
- `docs/next-major/SETTINGS.md`: regenerate from the catalogue (active keys only; one line pointing to the tolerated-retired list).
- All phase folders → `docs/history/<phase>/`, unchanged content, history README updated. Keep `docs/decisions/`.
- `AGENTS.md`: one line pointing agents to `docs/OPERATING_POLICY.md` as the authority and stating that values in retired settings, fixtures or history are never requirements.

## 7. Risks and rollback

| Risk | Mitigation |
|---|---|
| A dashboard or automation uses a retired legacy entity | Owner check before PR B; entity list in the PR; entities can be restored by reverting the retirement |
| Removing validation accepts a garbage retired value | Harmless: nothing reads it; rollback to 0.17.1 would reject it — prevented because retired values are no longer editable at all |
| `export_headroom_kw` deleted by mistake with the others | Explicit equivalence test (#4) |
| Smart-only (D2) changes request pattern | Bridge falls back to fixed 30 min without a valid plan; request budget unchanged; approval gate |
| Docs move breaks links | Link check in PR A |
| Rollback | Reinstall Controller 0.17.1 (HACS/manual): entry major version unchanged, all stored keys present with owner values, controller store format unchanged. Bridge untouched by A–C |

No live Home Assistant change, deployment, cloud request or heater operation
is part of any step; each needs separate owner authorisation.
