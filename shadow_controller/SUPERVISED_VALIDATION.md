# Later supervised qualification — not executed

Phase 2A has no command path. The owner accepts occasional manual recovery after
serious outages; universal automatic Schedule handback is not required. This does
not approve live tests, unsafe setpoints or changes to native safety functions.
See CONTROL_AND_RECOVERY.md for source findings and the unverified factory reset.

1. Preserve the known programme, 70°C target and 10°C T-Comfort. Confirm model,
   firmware, clock/DST, applicable manufacturer guidance and the supported app
   recovery route. Do not treat power cycling as reset or a generic software
   temperature range as device-specific approval. No covers or hardware changes.
2. Observe the shadow planner with the owner's load-tested meter direction,
   confirmed Tariff 93 and normal 30-minute temperature polling. Check representative
   morning-ready/shortage, sunny/cloudy, summer/winter, weekend and outage cases.
   Accept the bottom sensor as the planning reading; no new sensor is required.
3. With a NEW explicit approval, test one existing Manual request at an approved
   storage target. Budget a fresh pre-read, one write and bounded confirmation;
   account for refresh/replay overhead. Do not resend after timeout or ambiguity.
   Expect thermostat hysteresis and do not infer physical success from a POST.
4. Separately verify a real stop/park mechanism. Manual at 70°C can maintain it
   continuously. Restoring Schedule during an active window can continue heating.
   A 40°C morning threshold is never a command to store at 40°C. Keep Off out until
   its protection, resume and state semantics have been specifically approved for
   supervised testing. No guessed boost/On/reset endpoint or rapid mode toggles.
5. When communications work, qualify native Schedule handback through vendor mode,
   unchanged programme/target/T-Comfort and subsequent observed operation. Cmd 17
   alone is not proof of programme retention or power resume. Do not adjust T-Comfort
   to make the control design work. Keep native thermostat and hygiene authoritative.
6. Test one bounded ownership/confirmation cycle, duplicate intent handling,
   restart reconciliation and unexpected owner intervention. Existing grid export
   includes any heater load; a 3 kW load change must not induce repeated switching.
   Record supervised temperature changes to refine the planning margin later if
   observations are reliable; do not invent power or stratification measurements.
7. Under a separately reviewed plan, exercise communication-loss reporting and
   human recovery. Stop new writes, retain uncertain state and alert the owner.
   Manual recovery is an accepted risk; an unreachable app is not an independent
   recovery route. If no owner reset/recovery procedure can be verified, obtain
   Thermann/qualified technician advice rather than assuming default 65°C heating.

Only after these focused qualifications should an execution adapter be proposed.
EMHASS is optional later and must not publish directly to heater-command topics.
Nothing here authorises live commands, lock resets, deployment or schedule edits.
