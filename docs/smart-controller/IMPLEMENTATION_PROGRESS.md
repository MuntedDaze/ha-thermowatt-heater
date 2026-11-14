# Smart controller implementation checkpoint

Branch: `codex/smart-controller-next`.
Baseline: `1b29be165ddc61eb0b2e64a69eea9a435f7f7a53` (PR #27, unchanged).
Owner request: implement the Thermann brief, backend first; Fable owns dashboards.

## Boundaries

Development and synthetic offline tests only. No merge, deployment, live cloud,
MQTT, credentials or heater operation. Bridge 1.3.13 and controller 0.9.1 release
candidate are preserved; this branch is development work, not an install package.
Keep untracked `review-1b29be1/` and `uv.lock` untouched.

## Plan and status

1. Implemented: sustained optional weekend import returns to Manual 45 even
   with a sunny forecast; full-cover ten-minute qualification avoids buying
   discretionary partial-grid heat. Passing clouds retain five-minute debounce;
   ordinary weekend spacing remains (up to 15 minutes of exposure after a start).
   Only peak withdrawal/meter-loss OFF bypass spacing; confirmation/auth guards
   remain. Future status cannot authorize a command or poison the watermark.
2. Pending: generic verified CT power/energy, source times and conservation.
3. Pending: event telemetry, restart-safe measured energy/thermal calibration.
4. Pending: bounded adaptive polling shadow comparison; fixed polling unchanged.
5. Pending: economic comparison scenarios and guarded planning improvements.
6. Interface/documentation only: Fable implements dashboards separately.

## Resume

Check `git status --short`, branch and `git log -5 --oneline` before editing.
Read this checkpoint, the source and relevant tests; do not repeat the audit.
Audit sources inspected: ENGINEERING-AUDIT, DECISIONS-AND-PLAN,
POLLING-AND-THERMAL and results in `review-1b29be1/`.
Python 3.12 is available at
`C:/Users/jacob/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`.
Set `PYTHONPATH` to the absolute `.test-deps` directory for pytest/Ruff/mypy.
Workflow definitions: tests.yml, shadow-controller.yml, deployment-readiness.yml.
Native Docker/HA and Supervisor checks must run in isolated CI if Docker is absent.

## Evidence

Initial local HEAD and GitHub PR #27 head match the audited SHA. PR #27 remains
open/draft. No tracked owner edits were present. Tests and subsequent commit
anchors will be recorded here at each increment.

Increment 1: five new regressions ran against baseline: three reproduced bugs,
two existing guard behaviours passed. Full suite: **998 passed** (Python 3.12).
Ruff lint/format on project source, both workflow strict mypy targets,
compileall and Bash syntax passed. The untracked audit replay scripts do not
pass project Ruff rules; excluded from local checks, not modified or committed.
Docker is absent: native amd64/aarch64, HA and Supervisor matrices await CI.
Initial full baseline run: 992 passed, one overnight-baseline simulation failed;
the same test passed in isolation and the full post-change suite passed.
Increment 1 commit: find by subject `Fix optional import withdrawal and protective peak OFF`.
