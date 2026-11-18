# Code and settings audit (controller 0.17.1, bridge 1.4.1)

Date: 19 November 2026. Behaviour-preserving cleanup only; heating-policy
changes are in the separate solar-delay (0.16.2) and weekend (0.17.0) PRs.

Classes used below: **Required** (active control or safety), **Legacy**
(kept for saved installations/rollback; no effect in the recommended
configuration), **Developer** (diagnostic, comparison or test only),
**Duplicated**, **Unused** (no reference anywhere).

## What changed in 0.17.1

| Item | Before | After | Why it is safe |
|---|---|---|---|
| Back navigation | Submenus (Electricity Tariffs, Solar & Meters, Advanced/System) had no way back | Each ends with **← Back to main menu** | Menu step only; nothing is saved |
| Polling page | 9 fields: mode + 6 overlapping adaptive/preview switches + 2 data ages | **Cloud polling mode** (Smart recommended) + the 2 data ages | Fields moved, not removed; stored keys unchanged |
| Legacy page (Advanced → Legacy and developer settings) | Legacy items mixed with active ones | 6 pre-Smart polling settings, the three-state record and the 3 no-effect weekend settings | Same keys, same entities, same validation; descriptions state exactly when each still has an effect |
| Harmless preferences locked while Automatic is on | Low-water warning, pre-peak observation minutes and the no-effect weekend keys needed Automatic OFF | Editable while on (`SAFE_WHILE_ACTIVE`), still fully validated and preserved on Restore | None chooses a command, target, meter meaning or price |
| CT-free record help | Told owners to hand-assemble a record | Points to the guided setup; clearing withdraws | Text only |
| `model._present`, `Controller.holiday_window` | Unreferenced since 0.9.0 | Removed | Only a frozen 0.7.0 readiness fixture referenced them |

Not changed: stored option keys and defaults, native setting entities and
IDs, the retired-settings registry clean-up, commissioning gates, command
limits, the bridge, MQTT identities and storage.

## Polling: what actually takes effect

| Setting | Where | Effect with Smart/Minimum/Fixed 30 | Class |
|---|---|---|---|
| `polling_mode` (controller) | Advanced → Cloud checks | Selects v3 Smart/Minimum/fixed plans | Required |
| `polling_mode` (app option) | Thermann Hot Water app | Enables the bridge's v3 scheduler | Required |
| `adaptive_polling_enabled`, `event_aware_polling_enabled`, `owner_change_check_minutes` | Legacy page | None (only with **Keep existing**) | Legacy |
| `adaptive_polling_shadow`, `adaptive_poll_heating_minutes`, `adaptive_poll_stable_minutes` | Legacy page | None ever on real requests (advisory comparison) | Developer |
| App `adaptive_polling_enabled/qualified`, `event_aware_polling_qualified` | App options | None when the app's mode is Smart/Minimum | Legacy |
| `status_max_age_minutes`, `grid_max_age_seconds` | Cloud checks | Freshness limits | Required |

**The controller and the app have two controls for one behaviour.** Smart
needs both set to Smart. 0.17.1 says so in the help text. Proposal (not
implemented, it would change polling without an explicit choice): when the
controller is on **Keep existing** and the app publishes
`polling_preference = smart`, follow the app and report it. Needs owner
approval.

## Commissioning acknowledgements

| Setting / control | Effect | Class |
|---|---|---|
| `controller_four_state_qualified` | Gates every command (OFF/45/62/70) | Required |
| `controller_three_state_qualified` | None: production always requires four-state qualification (`requires_four_states=True`) | Legacy → moved |
| `controller_bridge_qualified` | None since 0.9.0 (already Retired) | Legacy |
| `ct_free_solar_verification` | CT-free solar identity; written by the guided page | Required |
| CT-free setup: *confirm direction* and *accept experimental* | Two separate acknowledgements on one form | Kept: they confirm different facts. Merging them is a commissioning-UX decision for the owner |
| `heater_meter_verification` | Dedicated-CT identity | Required |

## Settings inventory (99 keys)

- **33 Retired** (group `Retired`, no control since 0.8.0/0.9.0, entities
  already removed, values kept for rollback): morning thresholds/times,
  shower, planner tuning, native schedule clock, `paused`,
  `controller_bridge_qualified`, `controller_min_heating_minutes`,
  `controller_min_rest_minutes`, `controller_execution_latency_minutes`, …
  Kept: removing stored keys would break rollback and saved-option checks.
- **10 Legacy/Developer**, now on the Legacy page (listed above).
- **Remaining 56 Required**: hot-water roles and times, tariffs and clock,
  forecast inputs, equipment, weekend window, peak policy, guards,
  commissioning and budgets.

Locks: 57 settings plus the sensor mappings still need Automatic OFF to change. They decide where commands
go, whether they may be sent, how often, or what a measurement or price means.
That list was reviewed; only the five keys in `SAFE_WHILE_ACTIVE` met the
"never chooses a command, target, meter meaning or price" test.

## Code areas reviewed

| Area | Finding | Class / action |
|---|---|---|
| `simple_policy.py`, `controller.py`, `executor.py` | Active policy, gates and I/O | Required |
| `polling.py` (`PollingShadow`) | Advisory comparison shown in diagnostics; never requests HTTP | Developer, kept (report uses it) |
| `adaptive.py` `make_plan`/`event_plan` | v1/v2 plans for **Keep existing** installations | Legacy, kept |
| `thermal.py`, `learning.py`, `performance.py` | Read-only observer/learning; affects planning only when qualified | Required/diagnostic, kept |
| `naming.py` `RETIRED_SENSORS`, `__init__._remove_retired_entities` | Registry clean-up for retired entities | Legacy compatibility, kept |
| `tools/readiness/fixtures/thermann_shadow_0_x` | Frozen old releases for upgrade tests | Test-only, kept |
| `tools/*_replay.py` | Reproducible evidence; results checked by tests | Developer, kept |
| `model._present`, `Controller.holiday_window` | Unreferenced | **Removed** |

A whole-repository scan found no other unreferenced module-level function,
class or constant, and no other unreferenced method (Home Assistant entity
hooks excluded).

## Proposals left for owner decision

1. Single polling control (above).
2. Retire the 10 legacy keys' entities in a later release, once the owner
   confirms no automation or dashboard uses them (the retired-settings
   mechanism removes their entities, so this is not behaviour-neutral).
3. Merge the two CT-free acknowledgements into one.
