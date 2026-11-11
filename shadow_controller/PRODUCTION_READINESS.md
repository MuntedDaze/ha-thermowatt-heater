# Production-readiness checklist — 0.6.1

Legend: **Done** = implemented and tested offline · **Gate** = needs owner
participation or approval · **Risk** = accepted or open limitation.

## Requirements

| # | Requirement | Status | Where |
| --- | --- | --- | --- |
| 1 | Manual 70 °C permit / software OFF park; no setpoint or Schedule writes, no mains switching, no fallback windows | Done | `controller.py` |
| 2 | Resume from OFF only via guarded `Manual:70` (explicit 70); OFF status with an unusual setpoint must not break polling | Done in bridge 1.3.9 (PR #12); **Gate**: merge and install | `thermowatt_bridge.py` |
| 3 | No native Schedule configuration required | Done (empty-Schedule commissioning removed) | `controller.py`, settings |
| 4 | OFF target rule: 70 or no usable value means resume; a usable other value means owner override (never silently reset); resume confirmed only at Manual 70 | Done (controller and bridge) | OFF tests |
| 4a | Only `Manual:70` and `off` can reach the heater (bridge allowlist, default policy); legacy commands only by explicit choice | Done (PR #12, merged) | allowlist tests |
| 4b | OFF read correctly (`Cmd` 8, seen in T3) | Done in bridge 1.3.10 (PR #15); **Gate**: merge and install | `test_command_refresh_1_3_10.py` |
| 4c | Commands practical between polls without blind execution: one bounded pre-command status read, every rule re-checked on it, failures never executed | Done in bridge 1.3.10 and controller 0.6.1; **Gate**: T3b | refresh tests, `test_bridge_controller_compat.py` |
| 4d | An app change since the last poll is never overridden by a command | Done (bridge mode re-check; controller owner override) | owner-change tests |
| 5 | Protective heating while OFF never interrupted; no command while it runs | Done | protective tests, closed loop |
| 6 | Planner, tariffs, DST, solar, deadlines and budgets unchanged | Done (all 0.5.0 closed loops pass) | `test_controller.py` |
| 7 | Persisted intents, no retry, restart reconciliation, owner override priority | Done | unchanged tests plus OFF variants |
| 8 | Planner never publishes; exactly one module can | Done (AST test) | `test_shadow_model.py` |
| 9 | Disabled controller silent; storage written only on change | Done | disabled tests, real-HA check |
| 10 | Fresh install incapable of control | Done | fresh-install tests, real-HA check |
| 11 | HA-native UI, notifications, recovery guidance for OFF | Done | dashboard, `RECOVERY` |
| 12 | Commissioning with gates and rollback | Done | [COMMISSIONING.md](COMMISSIONING.md) |

## Outstanding physical qualifications (owner)

1. ~~T3 with bridge 1.3.9~~ — done 12 Nov 2026: OFF = `Cmd` 8, target 70 kept;
   `off` and `Manual:70` work; 60 s freshness made commands impractical.
2. **Upgrade to 0.6.1** (Stage A, control off).
3. **Bridge 1.3.10 and T3b** (Stage B2): stale-status `off` and `Manual:70`
   through the refresh path, duplicate and policy checks, power steps.
4. Supervised trial, then production.

## Remaining risks

- **OFF readback unknown.** What OFF reports (setpoint and `WaterHeaterSts`) has
  never been seen by the bridge. A fixed usable value other than 70 would make
  every resume pause for the owner (safe, but it needs a decision). T3 records it.
- **API equivalence unproven.** `/manual` from OFF is assumed to resume like the
  app's ON. If not, the command is confirmed as not applied and control locks,
  with no retry.
- **Element sensing** is empirical, and its meaning while OFF is unknown. The
  meter step is the physical check.
- **Cloud dependency.** A POST 401/403/429 auth lock means manual recovery
  (accepted).
- **Model limits.** Closed-loop results use a simple tank model.
- **The 1.3.8 bridge must not be used for OFF parking:** an OFF status with an
  out-of-range setpoint fails its polls. The controller cannot command 1.3.8
  anyway, because the bridge-flag gate blocks it.
