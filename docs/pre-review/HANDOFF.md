# Focused independent-review handoff

Branch `codex/polling-owner-readiness`, stacked on preserved draft PR #35 exact
`8d2b1e4a8c2c52818b73ddb082b7625c789b4425`. Candidate bridge 1.3.16 / controller 0.12.0.
No existing tested PR branch/worktree was modified. No merge, install, live HA,
vendor access/authentication/MQTT, heater command or automatic enable occurred.
Public-release administration and unrelated features remain out of scope.

## Implemented delta and evidence

| Requirement | Result | Sources / evidence | Outstanding gate |
|---|---|---|---|
| Fewer practical CT-free operations | Purpose-aware quiet checks and real-decision alignment; active half-hour observations | `adaptive.py`, `executor.py`, bridge `thermowatt_polling.py`; category replay/tests | Real request, comfort and owner-delay trial after approval |
| Preserve command/temperature safety | Passive lease affects only passive alert age; command guards/confirmation unchanged; temperature still expires | Controller freshness/confirmation regressions; v2 bounds and night-owner tests | Independent safety review and physical qualification |
| No silent longer polling on upgrade | New bridge quiet qualification and controller permission default false, in addition to old adaptive gates | Config/options/upgrade tests; v1 unchanged; no v2 capability sends no plans/fixed fallback | Explicit informed selection of owner-change bound |
| CT-free required economics | Verified raw grid export plus forecasts can inform required off-peak timing, never inferred heater credit | `simple_policy.py`, runtime snapshot; raw-export/no-optional test | Actual GoodWe sign/units/forecast mapping |
| CT-free predictions | Conditional nominal duration only; no physical ON/OFF or completion clock | `performance.py`, sensor/map/dashboard and fresh/stale tests | Real comfort/thermostat/draw evidence |
| Authentication | Investigated session/refresh flow; no heuristic/cooldown/retry/credential changes | Idle-tick/no-keepalive and refresh-failure lock tests | Vendor inactivity lifetime remains unverified |
| Multi-day comparisons | Fixed30/fixed60/quiet60/quiet90, CT/no-CT, all HTTP categories and deficits disclosed | WEEK_RESULTS.json and reproducibility/conservation/service tests | No synthetic claim of real bill/API savings |
| Owner source staging | Exact-commit source-only helper, dirty-cache/identity refusal and immutable local pin | Disposable Git tests; actual Supervisor load/catalog/schema smoke in isolated CI | Advanced procedure, actual version/console/source checks; no live install verified |
| Exact owner files | Reproducible local ZIP from committed paths with SHA256 manifest, no runtime/private state | `build_owner_bundle.py`, bundle tests | Final reviewed SHA/hash and owner approval |
| Beginner experience | Plain README, everyday names, CT-free explanations, 13-step owner guide and success checklist | Source/labels/template/schema/entity checks | Actual desktop/mobile/frontend visual review |

[Polling report](POLLING.md) explains the rejected 40-minute-phase experiment,
all category savings and explicit detection/unknown-temperature trade-offs.
The full suite/static and final-head CI evidence belongs in the new draft PR
and completion report. Do not infer it from the preserved PR #35 checkpoint.

## Reviewer focus

- V2 purpose/owner bounds, separate default-off server/client permission, lease
  loss and monotonic scheduling; previous v1 qualification must not grant v2.
- The controller’s validated quiet deadline must never enter command `gates`,
  temperature freshness, owner classification or confirmation authority.
- Pre-peak observation matches the actual two-minute OFF lead, without an early
  disposable read. Required temperature observations stay on the tested schedule.
- Raw local export informs required off-peak cost only. No CT means no optional
  solar authority. Mapped CT loss stays a notified fault.
- Metrics distinguish passive stale temperatures from required-plan deficits and
  report stale-command blocks/outage peak energy instead of suppressing them.
- Owner helper edits only a verified clean existing repository source checkout.
  It never installs/starts containers or edits private settings/auth/guard stores.
  Review the version-dependent Supervisor source-cache method before approving it.

## Remaining limits and owner sequence

Independent safety review comes first. Real manufacturer/native 45/62/70 behaviour,
compliant storage hygiene, cloud confirmation and app interventions need separate
supervised qualification. Real refresh-token inactivity limits are unknown; auth
failures stay locked. A single probe cannot prove tank-wide reserve or physical
OFF, and 60/90-minute quiet checks can miss short app changes.

Then separately approve the [owner installation plan](OWNER_INSTALLATION.md):
sealed backups, same stopped bridge source pin/update, preserved credentials/
tokens/guards/options/IDs, controller/dashboard upgrade while disabled, actual
mapping/tariff/clock checks, read-only observation, supervised four-state and
CT-free automatic trial. Start with fixed-30; only later approve event-aware 60
if its detection trade-off and real request behaviour are acceptable. A future
Shelly adds mappings/qualification, not a new installation. Learning remains off
until real clean held-out evidence is sufficient.

No release/tag/licence, history rewrite, credential rotation or public promotion
is included. Existing redacted historical security findings remain unchanged.
Progress and resume instructions: [checkpoint](PROGRESS.md).
