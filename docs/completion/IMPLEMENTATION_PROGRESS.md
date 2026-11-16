# Thermowatt existing-installation completion checkpoint

Baseline: main `b8de33673691e1c05cc3d86311cf88a9f400e02c`, after merged PR37/38/39.
Owner-installed bridge 1.3.17/controller 0.14.0, working read-only integration and
Shadow Mode, GoodWe and EMHASS. No fresh-install assumption or live inspection.
Branch: `codex/complete-existing-installation`; candidate controller 0.15.0,
bridge 1.3.17 unchanged. Final exact source/CI/review/merge evidence belongs in
the completion PR and final report, avoiding a self-referencing SHA commit.

Implemented: CT-free solar commissioning identity, genuine grid samples without
nominal heater credit,10-minute continuous withdrawal, confirmed15-minute optional
cooldown, durable protective exit independent of pending intent, unknown-diagnostic
blocking, session retirement on owner intervention/restart, conservative legacy
counter migration, local grid-event evaluation, nonzero provisional load fallback,
morning availability evidence and small existing hot-water dashboard additions.

Focused fault tests exercise the actual executor/bridge with mocked delayed
cloud acceptance, meter loss and restart: one START/one OFF, no replay.
Independent review identified and implementation corrected missing-diagnostic,
unqualified-session, legacy-counter, owner-session and baseline-quality findings.
Final diff review and complete final-head CI must confirm those corrections.

Validation required before merge: full pytest including refreshed deterministic
reports, Ruff/format, strict mypy targets, compileall/generated consistency/Bash,
Python 3.12/3.13/3.14, actual HA 2026.10.4/2026.11.1 and configuration frontend,
combined dashboard/no-solar/CT0/3, native amd64/aarch64 image/MQTT/lifecycle/demand,
Supervisor 2026.10.5/2026.11.0. A pending/failed/unavailable check blocks merge.

The owner's shared checkout and untracked review/lock files are untouched. Work
uses an isolated writable source copy because the shared `.git` is read-only.
GitHub source/PR/CI/merge use the available repository connection when shell
networking is unavailable. No owner HA, real MQTT/vendor credentials, automatic
enable, authentication generation or physical heater operation is authorised.

Next checkpoint: finish simulations, final independent review and all CI; merge
only the exact validated head, verify main and provide the normal in-place guide.
Physical commissioning, vendor-session evidence, CT installation/qualification
and automatic activation remain owner-controlled, separate from code completion.
