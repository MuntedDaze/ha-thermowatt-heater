# Configuration usability checkpoint

Draft PR: https://github.com/MuntedDaze/ha-thermowatt-heater/pull/38
Branch: `codex/configuration-usability`, based on merged PR #37
(`bf1ba0d2e705d21201669141d3517473e33f2710`). Fable's separate worktree is untouched.

Controller UI candidate 0.14.0; bridge unchanged at 1.3.17. No controller, command,
tariff-engine, saved household default, qualification, native entity or storage
schema changes. Owner 45/62/70 strategy remains fixed. The Configure forms retain
all saved/retired/unknown values and mappings; native setting IDs/units stay put.

Implemented and documented:

- Hot Water / Electricity Tariffs / Solar & Meters / Advanced/System menus.
- Plain labels and native inline help for all 54 active options and 15 mappings.
- Native selectors, precise cents/percent display conversion, equivalent-time
  preservation, genuinely optional commissioning text and clearable mappings.
- Guided draft weekly/seasonal schedules: days, months, category, optional price,
  add/edit/confirmed removal, explicit final save, existing full validation and
  active-control locks. Empty/invalid drafts remain editable and never save.
- Advanced JSON remains available. One existing tariff engine is used.
- Focused translation generator/check; legacy dashboard generation delegates to
  it instead of destroying descriptions. Dashboard/package files are unchanged.
- Beginner README/settings guide, owner/forecast navigation updates and five
  inspected screenshots with exact CI/source provenance.

Verification:

- Full local suites passed at earlier increments (1,498 then 1,499 tests);
  final full suite is running/recorded in the PR, expected 1,500 tests.
- Ruff lint/format, both strict mypy checks, compileall, Bash syntax, JS syntax
  and generated translations pass. All existing workflows were inspected.
- Actual HA 2026.10.4/2026.11.1: no-op saves for every option, all IDs and unknown
  extension values retained; converted edits, optional clearing, invalid targets,
  invalid/empty/cancelled tariffs and protected-setting locks verified.
- Real Chromium at desktop/phone widths: all 12 pages, visible labels/help,
  no horizontal form overflow, and actual unchanged saves of all 10 settings/
  mapping pages. Both versions passed at code head
  `8d9eff2bdbe1a24775649562de11ed74a0e20256`. Representative screenshots manually
  inspected; corrected an observed Markdown numbering defect and phone headings.
- Browser/HA tests have no external network, no bridge or MQTT and deny all service
  commands. Synthetic browser auth is private and excluded from artifacts.
- Final-head CI results and tested SHA are recorded in PR #38 after this commit;
  never infer final-head success from an earlier run. Existing native amd64/
  aarch64 MQTT/lifecycle/demand checks, Supervisor schemas, HA migrations,
  combined dashboard and Python 3.12/3.13/3.14 checks remain required.

Implementation is ready for focused review once all final-head checks pass. No
remaining production change is authorised: keep draft/unmerged. No installation,
owner HA/vendor connection, real authentication, MQTT/cloud command or heater
operation occurred. Human novice testing, other themes/browsers and any owner
installation are separate follow-up work, not claimed complete here.

Preserve owner untracked `review-1b29be1/` and `uv.lock`. Python executable:
`C:/Users/jacob/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`.
Set `PYTHONPATH` to the absolute `.test-deps` directory locally. Git mutations/
network use the configured sandbox escalation. No subagents were requested.
