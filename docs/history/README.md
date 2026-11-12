# History

Earlier reviews, reports and upgrade notes, kept unchanged for reference: why things are the way they are, and what was tested. Current instructions are in the main [README](../../README.md), the add-on [DOCS.md](../../thermowatt-heater/DOCS.md) and the controller [guide](../../shadow_controller/README.md).

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
