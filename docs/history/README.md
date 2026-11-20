# History

Earlier reviews, reports, plans, upgrade notes and evidence, kept unchanged for reference: why things are the way they are, and what was tested. **Nothing here is a current requirement.** Requirements are in [OPERATING_POLICY.md](../OPERATING_POLICY.md); a value, target or deadline found only here (for example the cancelled 45 °C-by-06:00 / 42 °C-by-07:00 morning reserve) must not be treated as current. Current owner instructions are in the main [README](../../README.md), the add-on [DOCS.md](../../thermowatt-heater/DOCS.md) and [docs/owner/](../owner/).

## Development phases (moved here on 20 November 2026)

Each folder was a development checkpoint; its replay evidence (`*.json`) is still checked by the tests that reproduce it.

| Folder | About |
| --- | --- |
| `audit-remediation/` | Independent-audit remediation (1.3.17), operations and parked-OFF review |
| `audits/` | Post-release audit and upgrade notes for bridge 1.4.1 |
| `cleanup/` | 0.17.1 settings cleanup audit |
| `completion/` | Controller 0.15 completion, interfaces and upgrade |
| `configuration/` | Configuration-form redesign and screenshots |
| `dual-storage/` | 45/62/70 dual-storage design (0.12–0.13) and simulations |
| `final-integration/` | Adaptive polling, learning, tariffs and week replays |
| `next-major/` | 0.16 / 1.4 evidence, polling comparisons and progress |
| `owner-report/` | Owner report of 19 November 2026 |
| `pre-review/` | Pre-review installation, polling and failure replays |
| `smart-controller/` | CT commissioning, economic comparisons and simulations |
| `solar-delay/` | 0.16.2 morning solar delay investigation and settings review |
| `weekend/` | 0.17.0 weekend comfort window design |
| `controller/` | Also holds the superseded 0.6–0.9 strategy, commissioning, settings audit, dashboard contract and thermal-model notes |

## Bridge (`bridge/`)

| File | About |
| --- | --- |
| `UPGRADING_1_3_3.md` … `UPGRADING_1_3_11.md` | Per-version upgrade notes. 1.3.9–1.3.11 contain the T3 / T3b / T3c supervised test procedures |
| `CLOUD_DIAGNOSTICS.md` | Why old errors were hidden, and the fixed diagnostic codes |
| `SECURITY_REVIEW.md` | Security review, including the historical key and token-storage risks |
| `DEPLOYMENT_READINESS.md` | Container, MQTT and Supervisor test evidence and its limits |
| `THERMANN_CONTROL_REVIEW.md` | Early review of Thermann compatibility and command semantics |
| `PHASE1_FORK_REVIEW.md`, `PHASE2_CONTROL_DESIGN.md` | Fork comparison and early control design |

## Controller (`controller/`)

| File | About |
| --- | --- |
| `CONTROLLER_REFERENCE_0_6.md` | The full 0.6 technical reference (bridge requirements, state machine, gates) |
| `COMMISSIONING_0_6.md` | The full 0.6 commissioning runbook with every stage procedure |
| `STAGE_4A_CONTROL_METHOD.md` | How Manual 70 / OFF was chosen; T1 evidence |
| `NATIVE_ON_OFF_REVIEW.md`, `LOCAL_CONTROL_FEASIBILITY.md`, `CONTROL_AND_RECOVERY.md`, `SUPERVISED_VALIDATION.md` | Control options and recovery design |
| `PHASE2B.md`, `PHASE3A_0_4_0.md`, `STAGE_3B_3C_PROPOSAL.md`, `STAGE_A_INSTALL.md` | Planner development stages |
| `PRODUCTION_READINESS.md` | The 0.6 readiness checklist |
| `UPGRADING_0_3_0.md` … `UPGRADE_0_6_1_TO_0_6_2.md` | Earlier controller upgrade notes |
| `COMPARISON_0_3_0_VS_0_4_0.md`, `CYCLE_SCENARIO_RESULTS.md` | Generated planner comparison reports |

## Audit evidence (`audit/`)

`SYSTEM_AUDIT_2026-11-11.md` and `REVIEW_MANIFEST.md`, with sanitised Home Assistant and EMHASS configuration snapshots. Location, IP addresses, keys and account data are excluded.
