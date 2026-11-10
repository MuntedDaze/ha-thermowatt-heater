# Phase 2 — current architecture and owner decisions

Phase 2A continues on draft PR #9. The independent Thermann Shadow Planner 0.2.0
extends the original 0.1.0 code; Thermowatt v1.3.8 remains the sole cloud bridge.
No deployment, commands, authentication changes or native programme edits occur.

- Measurements: reported bottom temperature and vendor mode, GoodWe PV/house
  display, owner-tested export-positive HK1000 grid power, cloud health and poll age.
- Planning: morning 40°C decision threshold by 07:00 (never a storage setpoint),
  daytime 70°C storage scenario, solar opportunities and full off-peak backup.
  Use 315 L / 3 kW and a 30-minute margin; no speculative stratification model.
- Tariff: owner-confirmed Aurora 93, fixed AEST UTC+10. Weekday peaks 07–10 and
  16–21 AEST, all other times off-peak. Hobart DST display shifts automatically;
  weekend 16:00 is a comfort goal, not a tariff peak. The device clock is separate.
- Execution: FUTURE ONLY. Existing Manual, Auto/Eco/Off community contracts need
  focused source/physical qualification. Manual at 65–70°C is not bounded on/off;
  product app On/Off is documented, but its API resume/retention contract remains
  unresolved. See `shadow_controller/NATIVE_ON_OFF_REVIEW.md`. No guessed endpoints.
- Recovery: owner accepts occasional manual intervention during serious outages.
  Universal automatic Schedule restoration is no longer a design prerequisite.
  Preserve protections, confirm when possible, expose faults and supply verified
  human recovery guidance. A factory reset to 65°C is not established by evidence.

Read [the current implementation and limitations](shadow_controller/README.md),
[control/recovery evidence and future execution](shadow_controller/CONTROL_AND_RECOVERY.md)
and [the supervised qualification plan](shadow_controller/SUPERVISED_VALIDATION.md).
These supersede the earlier universal-automatic-fallback design assumption.
EMHASS may later propose optimised windows; it is not required or a safety layer.
