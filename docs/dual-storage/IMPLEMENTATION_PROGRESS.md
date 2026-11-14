# Dual-target development checkpoint

Branch: `codex/economic-dual-storage` from tested PR #33 head
`cf97d5eec4aca82d7faa6f21e3e7a20f9aaff41b` (1059 tests, 18 green CI jobs).
Original worktree; Fable's separate worktree/PR #32 and PR #27/#33 untouched.
Pre-existing untracked audit directory and uv.lock are not this work.

Owner-approved scope: four-state backend, sensible supported configuration,
backward-compatible migration, offline simulations and public documentation.
No merge, deployment, live cloud/MQTT, heater operation, credentials or licence
change. A separate draft PR targets `codex/smart-controller-next`.

## Increments

1. Implemented: bridge guarded OFF/45/62/70 transitions and controller state
   recognition. 1093 tests passed (1059 previous +34 protocol regressions).
   Every directed transition, confirmation, owner-mode mismatch and unsupported
   payload is covered; original six transitions retain their semantics. Ruff,
   both strict mypy targets and compileall pass. Native/HA matrices await CI.
2. Implemented: single coordinated required-62/optional-70 policy, strong-solar
   direct starts, useful-heat/standby/switching economics, native hysteresis and
   optional-budget fallback to required heat. Separate peak lockout and boost
   controls; CT-free required operation; owner 12h Override remains 70. OFF
   unconfirmed notification never claims electrical zero. Full suite: **1128
   passed** on Python 3.12; 35 focused dual-policy cases passed; Ruff, strict
   mypy targets and compileall passed. Existing mandatory-70 scenarios are kept
   as explicit compatibility fixtures. Native/actual HA checks await final CI.
3. Implemented: fresh-install defaults start unverified with no household entity
   mappings; migration preserves old explicit choices and effective defaults.
   Tank/power, closed temperature roles, peak/boost and economic preferences are
   HA settings. Target/model-tagged measured history uses a separate v2 store;
   legacy rows are preserved, unclassified and excluded from calibration.
   Telemetry schema 2 covers all four states and advisory poll reasons recognise
   normal/boost decisions and completions. Candidate metadata: bridge 1.3.14,
   controller 0.10.0. Full suite passed (1140 cases before two added polling
   cases); focused public-installation/polling cases passed, Ruff, strict mypy
   and compileall passed. Actual HA/native/Supervisor matrices still await CI.
4. In progress: 11 comparative cases / 33 replays implemented, including direct
   70, later top-up, cloudy/patchy/failed forecasts, draw, late boundary, weekends
   and CT-free operation. Equal service, terminal energy and request assumptions
   are explicit; conservation/reproducibility regressions pass. Public docs,
   installation/upgrade/rollback, household example and hygiene review pending.
5. Pending: full local/CI verification, draft PR and final handoff.

## Resume

Completed protocol commit: `fd40b33`. Policy/settings commit: `1972b16`.
Increment 3 commit subject: `Preserve upgrades and expose target-aware public configuration`.
Continue with comparative simulations and public documentation, then verify the
draft PR's complete CI matrix. No production action has been performed.
Draft PR: #34, target `codex/smart-controller-next`; increment 3: `201b870`.
Initial Python CI passed on 3.12/3.13/3.14. Actual HA found a harness assertion
that assumed an alternative always differed from the recommendation, despite
preserved historical defaults. Corrected to verify the actual flag accurately;
both HA matrices need rerunning. Native/Supervisor jobs still in progress.
New phase-local checkpoint is this file; retain PR #33's checkpoint unchanged.

Inspect branch/status/log first; never switch or alter another worktree. Continue
from the current increment, not another broad audit. Python:
`C:/Users/jacob/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`,
with PYTHONPATH set to the absolute `.test-deps` directory. Workflow definitions
remain authoritative; all Python/static, real HA, native amd64/aarch64 and
Supervisor checks must pass on the final head. Hardware 62-degree behaviour and
all new transitions remain physically unverified. Adaptive polling stays shadow
only; historical calibration stays diagnostic. Licence selection needs separate
owner approval; do not add a licence file.
