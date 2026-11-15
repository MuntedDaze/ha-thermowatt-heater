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

## Current checkpoint / resume

Draft PR #36: https://github.com/MuntedDaze/ha-thermowatt-heater/pull/36
Base remains PR #35 (`codex/thermann-final-integration`, exact8d2b1e4).
First implementation commit `7c9eb5b1e8cea7aa4f7f5d9d0f707944643eec34` is pushed.
The next finalisation commit includes clearer conditional display labels/form
help, actual Restore/Undo preservation, complete failure replays and owner ZIP
transfer/path-alias safeguards. No algorithmic expansion beyond this scope.

Delivered:
- Explicit default-off v2 quiet permission on BOTH bridge and controller, selected
  healthy owner bound30–90min; old v1 qualification cannot silently grant it.
  Missing v2 support/qualification sends no plans and uses fixed fallback.
- Stable confirmed baseline/Never-peak OFF holds, warm-baseline/mapped-CT checks,
  expiring monotonic lease and original fixed recovery. Active planning rejoins
  half-hour observations; observations align with real decisions/two-minute OFF
  lead.45min temperature and60sec bridge command prior remain separate/unchanged.
- Verified raw GoodWe export informs required off-peak economics only. Conditional
  continuous-heating duration never asserts ON/OFF or a completion clock.
- Actual Restore/Undo now calculates its cached preference set AFTER protected
  extensions, preserving timezone/service-window/poll/learning choices. Older
  unsafe Undo data containing protected keys is refused. No default is enabled.
- Eight ordinary week comparisons: CT-free447 vs713 requests(37.3% fewer),
  measured493 vs740(33.4% fewer) with quiet60, equal cost/service/target outcomes.
  Passive unknown temperature increases; required-plan unknown minutes stay12/0,
  same as fixed30. Owner-change detection45 vs15min in this phase; bounds and
  missed short changes explicit. Quiet90 is studied, not initial recommendation.
- Six failure weeks:45 dropped plans trigger actual fixed reads; Sunday refresh401
  leaves every strategy persistently blocked with zero subsequent HTTP. No auth
  generation changes or savings claim from unavailable control. Both JSON reports
  and legacy comparison are reproducible; deficits/cost/categories remain visible.
- Plain README,13-step Proxmox/HAOS CT-free owner guide, correct historic GoodWe
  AC mapping(total_power), visual-review checklist, later Shelly/recovery plan.
- Source-only staging helper: existing repository-backed identity, exact SHA,
  clean/public-origin/path checks, alias deduplication, local immutable named pin,
  recovery record; no container install/start/private options/auth edit. Local_
  or other-repository installations are refused pending their own reviewed plan.
- Exact-commit local ZIP/manifest builder; excludes runtime/private files, keys,
  .git/untracked files and historical audit payloads. Includes source and linked
  guides/generator. Owner checks ZIP and transferred helper hash before use.
- Actual Supervisor2026.10.5/2026.11.0 GitRepo.load/catalog/schema smoke added to
  isolated CI. Both native architectures and actual HA passed first-head checks.

Validation: full local **1403 tests passed**, plus latest25 focused owner/poll
cases after path-alias handling. Ruff lint/format, both strict mypy targets,
compileall/generated files and Bash syntax passed earlier; rerun final static/
link consistency as needed. No active exec sessions at construction of this
checkpoint. Final-head CI is still required; exact final SHA/26 jobs and bundle
SHA256 will be recorded in PR #36 / completion report rather than a self-referencing
post-CI commit. Never infer final success from7c9eb5b or the prior8d2b1e4 checks.

Remaining finalisation only: commit/push the final delta, inspect/resolve all
final-head CI and reviews, build the ignored `owner-staging/` ZIP from that final
SHA, verify its manifest/hashes and update PR metadata/handoff. Preserve
`review-1b29be1/`, `uv.lock`, all earlier draft branches and Fable worktree. Do not
merge/install/authenticate/operate. Independent review, actual frontend and all
physical/vendor/CT qualification remain outstanding; public distribution deferred.

Python runtime:
`C:/Users/jacob/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`,
PYTHONPATH absolute `.test-deps`. UTF-8 for text. Never print the embedded API key
(bridge line25) or historical keys. No subagents were requested/used.
