# Independent-audit remediation and normal installation handoff

The focused follow-up from reviewed94a7dd4 closes the unknown-current-state
parked-OFF warning gap. See [the short review handoff](PARKED_OFF_REVIEW.md) and
PR37 for its final-head test/CI evidence. All other findings remain as reviewed.

[Draft PR #37](https://github.com/MuntedDaze/ha-thermowatt-heater/pull/37).
Candidate **bridge 1.3.17 / controller 0.13.0**, branch
`codex/audit-remediation-normal-install`, based on preserved PR36 exact
`649491381cd58cbb8ad65210453f67c551934fab`. A new draft targets **main** so one
future approved integration can offer one normal update, rather than publishing
intermediate stacked candidates. [Integration strategy](NORMAL_UPDATE.md).

The full local independent report and its adversarial code/output/week evidence
were read. Source: `.audit-2026-11-15/REVIEW_REPORT.md` and accompanying files,
untouched. No broad audit was restarted. PR36 and earlier branches, including
Fable's separate4c078f0 worktree, remain preserved. No merge, live HA/vendor access,
authentication/MQTT, installation, actual heater command or enablement occurred.

Source report SHA256:
`eef7030c52d519a04207af11319cecc6881f74c763bf736eb579521a1a781509`.
The local report is not republished or modified by this remediation.

**Owner correction takes precedence:** retain Manual 45°C overnight/weekends,
Manual 62°C normal weekday storage, optional economical Manual 70°C and the existing
configured peak-OFF policy. Owner plumber discussion is recorded; this project
does not claim independently established compliance. F8 is documentation only:
no new restrictive temperature gate, hygiene monitor or policy redesign.

## Remediation matrix

The stage gates below describe what still needs independent/physical evidence;
implemented code and passing mocks alone do not grant operating permission.

| Finding | Fix / result | Evidence | Remaining risks and blocked stages |
|---|---|---|---|
| F1 cache pin | Removed installer/load-only smoke. Normal same-identity Update after a single approved integration into main; no branch repo or second bridge | Real Supervisor load/**pull**/catalog fixtures for both registered URL spellings and two versions; unchanged private fingerprints and repeat refresh/forward recovery. Historical bridge upgrade/entity tests retained | Read-only install awaits approved merge, same actual registered source/ID/version, verified backup; real VM/image restore remains untested |
| F2 parked-OFF outage | Last observed OFF and30-minute unmet permitted-heat timer persist across restart. Distinct fault warning, recovery runbook, tested-phone commissioning item and independent evaluation watchdog | Actual bridge backoff + restart through simulated peak windows, no early retry/peak bypass, one healthy restoration; cloud/auth/unavailable warning/reset/owner-hold tests | Blocks unattended CT-free automation until supervised outage, phone/watchdog and manual recovery are accepted. No working cloud path means no promised automatic restoration; total HA failure needs external monitoring |
| F3 inactive session | Existing request-driven refresh/guards unchanged. Seven complete days fixed 60-minute polling read-only, zero rejection/lock/hidden keepalive, independently accepted evidence; repeat at 90 | Quiet60/90 first-refresh rejection leaves guard blocked, no further HTTP, owner restore warning. Existing night owner-change/lease tests remain | Blocks longer adaptive polling only; vendor lifetime unqualified. Fixed30 remains the initial route |
| F4 false pending | Finish a due refresh before persisting uncertain heater intent. Refresh failure records refusal/nothing pending; recheck prior freshness/queue age after slow refresh. No refresh starts inside pending POST window | Timeout/connection/401/429, slow successful refresh, actual POST timeout remains pending; duplicate and restart do not repeat | Changed safety path needs independent review and supervised confirmation/restart qualification before commands/automation; no auth retry/lifetime relaxation |
| F5 missing devices | Empty valid discovery reports no_devices, fixed rediscovery; empty active set has a default deadline; first adaptive sync is inside tick exception boundary | Empty/reappearing devices, old deadlines/empty set and internal sync exception tests; no auth lock or busy loop | Needs integration CI and normal commissioning; no invented heater state from cached devices |
| F6 CT-free pause | Continue selected required heating without a valid CT rather than pausing on raw grid data containing unknown element draw. Economical start selection still uses available forecasts/export | Minimum$0.10 pause threshold over repeated CT-free decisions; original weekly outcomes reproduced exactly | Fewer pause opportunities without CT, intentionally; no optional solar authority or nominal element credit |
| F7 backoff race | No behaviour change: a queued command may await backoff; controller gates normally prevent publication | Existing guards and adversarial finding reviewed; F2 recovery tests respect actual backoff | Command may expire/refuse; never shorten backoff or promise instant restore |
| F8 requirements/strategy | Correct official requirements, manufacturer/native-cycle limitations and owner decision documented; agreed45/62/70 preserved | Configuration/policy regression for night/weekend45, weekday62, optional70 role and no new gate; source review confirms defaults/protocol unchanged | Independent compliance/native behaviour not established. Physical appliance/plumbing assessment remains separate; no new software restriction |

## Validation and evidence

Targeted offline regression is in `tests/test_audit_remediation.py`. It includes
both actual DST transition days with fixed-standard tariff and UTC event timing,
outage/restart/restore, quiet refresh rejection and explicit owner-strategy
preservation. Existing tests cover owner changes just after quiet observations,
exact-prior refusals, bridge budgets, pending outcomes and historical migrations.

The three full-week reports were regenerated after the fixes and are identical
to PR36, including all HTTP, energy, cost, targets, alerts and unknown-temperature
metrics. Synthetic request savings remain447 versus 713 CT-free and493 versus 740 measured at
60-minute quiet mode. They are not real session qualification or household bill evidence.

New read-only entities are **Controller last evaluated** and **Waiting to restore
heat since**. The seven-view map uses the actual generated registry names. The
optional notification-only watchdog example is checked with actual HA config
validation; no action is executed. Controller control remains independent of the
dashboard and optional appliance/CT channels.

Final suite/static/actual-HA/native/Supervisor checks are being completed. Record
the exact final SHA, all applicable final-head workflows and reviews in the new
draft PR/completion report; this checkpoint delegates that final evidence there
to avoid a self-referencing post-CI commit. Never infer success from PR36's checks.
Actual frontend usability and a full independent dashboard audit remain
outstanding; schemas, entity maps and templates do not substitute for them.

## Changed safety paths for the next reviewer

1. `thermowatt_bridge.py`: pre-POST authentication sequencing and refusal;
   genuine uncertain delivery remains persisted before send. Check boundary
   crossing, storage failure, lockout/quota and no replay.
2. `thermowatt_bridge.py`: empty-device recovery and contained adaptive sync.
3. `controller.py`: diagnostic last-observed state/timer, restart/reset and owner
   semantics. It must never become state/command authority.
4. `simple_policy.py`: no CT-free required-pause decision; required starts, peak
   priority and all guarded temperature roles remain unchanged.
5. Owner install/recovery, actual Supervisor pull fixture and explicit limits of
   mocked state preservation versus a real backup/image restore.

Start future owner read-only/automatic qualification at fixed 30-minute polling. Keep adaptive
and learned control disabled. Learning still requires a commissioned CT, clean
independent sessions, held-out validation and its separate existing qualification.
No release, licence, speculative packaging or public distribution is prepared.

[Owner guide](../pre-review/OWNER_INSTALLATION.md) · [Operations/inactivity](OPERATIONS.md)
· [Progress checkpoint](PROGRESS.md) · [Beginner README](../../README.md)
