# Focused pre-review checkpoint

Owner request: improve event-aware Thermann polling, excellent CT-free required
heating, reproducible HTTP comparisons and a concrete owner in-place staging /
installation guide. No broad audit or speculative public release work.

## Isolation and protected checkpoints

Original worktree `C:/Users/jacob/Documents/ChatGPT/ha-thermowatt-heater`, branch
`codex/polling-owner-readiness`, created from PR #35 exact reviewed/tested head
`8d2b1e4a8c2c52818b73ddb082b7625c789b4425`. PR #35 independently verified draft,
unmerged and unchanged. Fable's distinct worktree `.../ha-thermowatt-heater-fable`
remains on `fable/thermann-energy-dashboard` at `4c078f0`. Owner untracked
`review-1b29be1/` and `uv.lock` remain untouched. Preserve all older PR anchors.
New draft PR must stack on `codex/thermann-final-integration`.

No merge/install/live HA/vendor authentication/MQTT/heater operation. All new
authority default-off; exact-prior, command confirmation, auth retry/locks,
quotas, tariff verification, migrations and raw CT boundaries remain mandatory.

## Findings and focused implementation plan

1. Trace actual categories: CT-free v1's 30-minute ceiling cannot save ordinary
   reads while pre-decision reads ten minutes before a command expire under the
   bridge's unchanged 60-second exact-prior rule, adding command-refresh GETs.
   Refresh is request-driven, not an idle keepalive; retain its existing20-minute
   heuristic and fail-closed retry rules until independent vendor evidence.
2. Add explicitly enabled event-aware quiet periods, with a bounded configurable
   owner-change check interval (study60 and90 minutes). Keep v1 and the original
   fixed fallback, and the existing45-minute temperature validity. A confirmed
   stable baseline/OFF may hold its thermostat request without pretending its
   old temperature remains fresh. Extend no command-specific freshness gate.
   Align consequential observations to actual decision/boundary command times,
   coalescing pre-command checks where already allowed. Lease/restart/fault
   invalidation must select conservative reads/fixed recovery.
3. Required off-peak CT-free economics may use verified raw GoodWe export and
   forecasts, without crediting inferred element watts or enabling optional solar.
   Show explicitly conditional nominal durations, never physical ON/OFF or a
   promised wall-clock completion without CT evidence.
4. Compare fixed30/fixed60/improved adaptive over full weeks, account every HTTP
   category, service/cost/target/status/detection differences, and add focused
   stable-night/lease/auth/restart/fresh command tests. Disclose missed changes
   and vendor lifetime uncertainty, not just background-read savings.
5. Improve beginner README/settings/dashboard explanations and prepare a
   digest-verified exact-commit staging artifact / in-place same-slug bridge
   replacement method. Never create a second active bridge. Preserve tokens,
   guards/generation/options/entities; include rollback from Manual62 and later
   Shelly commissioning. No deployment is performed.
6. Run full existing/added tests, static checks and applicable final-head CI.
   Commit/push increments and new draft PR; leave all existing drafts unchanged.

## Resume

Implementation delivered locally (awaiting commit/final-head CI): explicit default-off quiet-period flag
and30–90min owner bound; v2 wire purpose/owner cap with v1 unchanged; active
temperature plans rejoin half-hour slots and pre-boundary reads align with the
real2min policy lead. Controller passive alert deadline is separate from all
unchanged command gates and45min temperature validity. Cold baselines and mapped
CT faults cannot use long quiet leases. Verified raw GoodWe export informs only
required off-peak economics. New nominal-duration sensor is conditional, never
ON/OFF or a wall time. Dashboard map/HA registry additions included.

20 new focused tests pass (night app changes30/60/90, quiet auth no keepalive,
failed refresh locks, fixed lease fallback, v2 limits, unchanged command freshness,
CT-free required export and nominal duration). Added separate bridge v2 qualification
(defaultfalse even for existing v1-qualified users); missing v2 support/qualification
sends no plans and selects fixed fallback. Translation/forms/registry updated.
Full1397 tests passed before that final server gate/metadata increment; latest140
focused tests pass. Final full suite and all final-head CI still required. Earlier
full attempt found missing new form labels; fixed and verified. Report regenerations
finished; both JSON files include critical-temperature/stale-command metrics.

First40min active experiment reduced HTTP but worsened CT-free outage timing/cost;
replaced with aligned active slots. Revised pre-cold-guard replay: no-CT447 vs713
and CT493 vs740 at quiet60, same cost/target outcomes; healthy owner detection
can take60min rather than30. Quiet90 is comparative, not initial recommendation.
Final regenerated values remain447/713 and493/740 at60, preserving required
temperature freshness/cost/target outcomes; passive temperatures intentionally
expire. Quiet90 comparison365/420 requests is not an initial recommendation.

Installation research: official HA repository IDs include URL#branch, so adding
a branch repository creates a different full add-on identity and cannot be the
in-place upgrade method. Official Supervisor2026.11.0 GitRepo.load preserves a
named local checkout, validates origin/fsck; pull uses the active branch. Prepare
a guarded source-cache checkout to a *local pinned review branch* in the existing
repository, then Supervisor restart/read catalog/update while the existing add-on
is stopped and watchdog/autostart off. This is advanced developer staging, not a
normal public-store install; needs explicit owner approval and actual-version
checks. Never delete/re-add the add-on or edit private auth/options JSON. Still
implemented: reviewable source-only helper, reproducible exact-commit bundle,
disposable-Git tests, actual isolated Supervisor load/catalog smoke and workflow,
13-step owner guide, plain README, full comparison regressions, version/changelog
candidate1.3.16/0.12.0. Helper never installs/starts a container or edits private
data/options/auth; source pin is version-dependent advanced staging and needs
owner approval. Remaining: first commit/push/new stacked draft PR, final local
tests/static/docs checks, fix any actual CI issue, final-head26 jobs, build local
owner bundle from final tested SHA and record SHA256 in handoff. No public release.

Read current branch/status before proceeding. Use
Python `C:/Users/jacob/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`
with PYTHONPATH absolute `.test-deps`; UTF-8 reads/writes. Never print the embedded
application key (bridge line25) or historical private keys. The previous phase's
1371 tests/26 CI jobs are evidence for8d2b1e4, not this new work.
