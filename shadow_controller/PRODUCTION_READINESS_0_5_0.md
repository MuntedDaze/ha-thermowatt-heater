# Production-readiness checklist — 0.5.0

Legend: **Done** = implemented and tested offline · **Gate** = needs owner
participation or approval · **Risk** = accepted or open limitation.

## Requirements

| # | Requirement | Status | Where |
| --- | --- | --- | --- |
| 1 | Manual 70 permit / empty Schedule park; no `/off`, no setpoint or Schedule writes, no fallback windows | Done | `controller.py`, `control_plan.py` |
| 2 | Guarded Manual at exactly 70 °C | Done (bridge 1.3.9, PR #12); **Gate**: merge and install | `thermowatt_bridge.py` (PR #12) |
| 3 | Planner never publishes; exactly one module can | Done (AST test) | `test_only_the_executor_can_actuate…` |
| 4 | Explicit, persisted, auditable state machine | Done | `controller.py`, HA Store |
| 5 | Unique persisted intent; no duplicates; restart never re-sends | Done | intent tests, real-HA check |
| 6 | Reconcile observed state with intent; unconfirmed writes never retried | Done | confirmation tests |
| 7 | App changes take precedence; unknown mode or target suspends | Done | override tests |
| 8 | Disabled never changes mode; re-enable inspects first | Done | disabled tests, real-HA check |
| 9 | Dwell, daily command limit (with comfort reserve), confirmation timeout, request budget; bounded settings | Done | gates, option-bound tests |
| 10 | Poll-aligned timing with latency reserve; on-demand rejected on evidence | Done | [CONTROLLER_0_5_0.md](CONTROLLER_0_5_0.md) |
| 11 | Hysteresis-aware starts; thermostat cut-off; no toggling | Done | hysteresis and cut-off tests |
| 12 | T1 sensor overshoot handled | Done | `SessionTemperature` tests |
| 13 | Antibacterial/protective heating never interrupted | Done (blocks writes, notifies) | unexplained-heating test |
| 14 | Faults stop commands, preserve state, notify, give recovery steps; no auth resets | Done | fault tests, `RECOVERY` texts |
| 15 | HA-native UI: master switch, override, acknowledge, status, readiness, cost, last command, bridge health | Done | dashboard *Automatic control* section |
| 16 | Notifications with cooldowns and restoration notice | Done | notification tests |
| 17 | Fresh install incapable of control | Done | fresh-install tests, real-HA check |
| 18 | Comprehensive offline tests, real HA Core, replay | Done: 852 local; CI all green | `tests/`, `shadow_ha_checks.py`, `replay_history.py` |
| 19 | Commissioning runbook with gates and rollback | Done | [COMMISSIONING_0_5_0.md](COMMISSIONING_0_5_0.md) |
| 20 | Local-only control report | Done | [LOCAL_CONTROL_FEASIBILITY.md](LOCAL_CONTROL_FEASIBILITY.md) |

## Outstanding physical qualifications (owner)

1. **Stage A**: install 0.5.0 directly over 0.3.0, with control off ([STAGE_A_INSTALL.md](STAGE_A_INSTALL.md)).
2. **Stage B / T3**: bridge 1.3.9 `Manual:70` and `Auto` against the real
   heater (latency, power steps, readback, request cost).
3. **Stage C**: empty weekly Schedule saved, with the old programme recorded.
4. **Stage D**: supervised cycles with planned-versus-observed review.
5. **Stage E**: production approval.

## Remaining risks

- **Element sensing** (`WaterHeaterSts` bit 0) is empirical. It is mitigated by
  the meter step, and confidence is shown.
- **Antibacterial cycle** timing under frequent Manual ↔ Schedule changes is
  product-level evidence only. The controller never interrupts unexplained
  heating.
- **Cloud dependency:**
  - a POST 401/403/429 locks bridge authentication, and recovery is manual;
  - vendor rate limits are unknown, so a budget and gates are enforced;
  - a cloud outage leaves the heater in its last mode (accepted).
- **Model limits.** Closed-loop results use a simple tank model; real
  stratification and draws will differ. The 30-minute latency reserve and comfort
  fallback cover typical cases, not every draw pattern.
- **Clock.** The heater's own clock no longer matters once the Schedule is empty.
  Tariff and deadline handling uses HA time (DST tested).
- **Upgrade path.** The 0.4.0 → 0.5.0 upgrade adds only default options and a
  new storage file. It is covered by the 0.2.0/0.3.0 → 0.5.0 real-HA upgrades,
  not a dedicated 0.4.0 fixture.
