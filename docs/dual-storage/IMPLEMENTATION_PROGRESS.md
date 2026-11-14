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
2. Pending: one coordinated normal-62/optional-70 policy, economic/hysteresis
   tests, optional budgets and strong-solar direct starts.
3. Pending: useful HA configuration, fresh-install defaults and preserving
   existing verification/options, thermal/history/telemetry/polling updates.
4. Pending: comparative simulations, public docs, installation/upgrade/rollback,
   household example, redacted public-distribution review and licence options.
5. Pending: full local/CI verification, draft PR and final handoff.

## Resume

Inspect branch/status/log first; never switch or alter another worktree. Continue
from the current increment, not another broad audit. Python:
`C:/Users/jacob/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`,
with PYTHONPATH set to the absolute `.test-deps` directory. Workflow definitions
remain authoritative; all Python/static, real HA, native amd64/aarch64 and
Supervisor checks must pass on the final head. Hardware 62-degree behaviour and
all new transitions remain physically unverified. Adaptive polling stays shadow
only; historical calibration stays diagnostic. Licence selection needs separate
owner approval; do not add a licence file.
