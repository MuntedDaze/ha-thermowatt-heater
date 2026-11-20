# Audit 20 November 2026 — operating specification and legacy cleanup

> Audit snapshot of main d137c4c (Controller 0.17.1, bridge 1.4.1). File paths
> are as they were at that commit; phase folders have since moved to
> `docs/history/`. Current requirements: [OPERATING_POLICY.md](../../OPERATING_POLICY.md).

Base: `origin/main` d137c4c (Controller 0.17.1, bridge 1.4.1), read from an
exported copy. Audit and report only: no code, settings, branch, PR, Home
Assistant or heater was changed. Not committed.

1. [Operating specification](1_OPERATING_SPECIFICATION.md) — Phase 1: the 12 scenarios, each with target, restrictions, settings, code location and approval status.
2. [Inventory](2_INVENTORY.md) — Phase 2: all 99 settings, entities, code areas, bridge options and contradicting documents, classified.
3. [Owner decisions](3_OWNER_DECISIONS.md) — Phase 3: **the one document to answer.** Confirmed policy as default, 4 questions.
4. [Cleanup plan](4_CLEANUP_PLAN.md) — Phase 4: deletions, retirements, compatibility, migration, tests, docs, risks, rollback.

Headline findings:

- The active controller already follows the cancelled-morning decision: nothing chases 42 °C, tops up in the morning or raises a 42/45 deadline alarm. The old values survive only as 4 stored settings, their validation (including cross-field rules), one unused helper, one entity label and several documents.
- F1: `export_headroom_kw` is labelled Retired but sets the 3.3 kW boost start threshold.
- F2: 32 inert retired settings are still validated on every save, so a bad stored value could block changes to active settings with an error about a field the owner cannot see.
- A pre-peak low-water notice (35 °C) can fire before the morning peak — owner decision 1.
- Two polling controls must both say Smart — owner decision 2.
- README and five controller documents contradict current policy; 12 phase folders have no single source of truth.
