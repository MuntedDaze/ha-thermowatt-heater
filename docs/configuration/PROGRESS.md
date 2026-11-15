# Configuration usability checkpoint

Branch: `codex/configuration-usability`, based on merged PR #37
(`bf1ba0d2e705d21201669141d3517473e33f2710`). Fable's separate worktree is untouched.

Scope: controller 0.14.0 configuration presentation only. Bridge stays 1.3.17.
No controller, command, tariff-engine, saved default, qualification or storage
schema changes. Owner 45/62/70 strategy and all IDs remain unchanged.

Implemented: four topical menus; all active fields have native inline help;
number/time/entity/dropdown selectors; precise cents/percentage conversions;
guided draft weekly/seasonal periods with existing full validation and locks;
advanced JSON retained; optional mappings can be cleared. Form translations have
their own generator so the legacy dashboard builder cannot overwrite the help.

Validation underway: full local regression/static suite, actual HA flow tests,
and real HA 2026.10.4/2026.11.1 frontend checks at desktop/phone widths. The new
browser job runs with network-none HA and a browser sharing that isolated
loopback namespace; all service commands are denied. Synthetic auth is private
and excluded from artifacts. Screenshots still need inspection; no claim of
completed visual validation yet.

Next: resolve any CI/browser findings, inspect screenshots, finish the beginner
UI guide and selected screenshots, run full final-head checks and update a new
draft PR. Keep it unmerged. No installation, owner HA connection, authentication
to the vendor, MQTT/cloud command or physical heater operation is authorised.

Preserve unrelated untracked `review-1b29be1/` and `uv.lock`. Python executable:
`C:/Users/jacob/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`.
Set `PYTHONPATH` to the absolute `.test-deps` directory for local checks. Git
mutations/network require the configured sandbox escalation. No subagents.
