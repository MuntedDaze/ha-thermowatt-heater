# Phase 2 — Home Assistant / EMHASS design only

No controller, automation, heater command, native schedule edit or deployment is
implemented here. Each live control capability needs separate owner approval and
supervised qualification. The integration supplies reliable read-only data and
existing control primitives; optimisation belongs in separate HA/EMHASS code.

## Outcomes and inputs

- Sufficient usable hot water by **07:00 local time**, without unnecessary
  overnight heating when a validated reserve estimate is adequate.
- Surplus solar is the first daytime heating opportunity; off-peak import is
  fallback. Comfort overrides a price/solar optimisation that risks shortage.
- Aim for **65–70°C before the actual weekday evening-peak start**, with separate
  weekend tariff handling. Do not hardcode 16:00 as a tariff boundary without the
  owner's tariff contract; around 16:00 comfort remains a household requirement.
- Use measured **net grid import/export**, with sign, units and phase aggregation
  validated, plus household/battery/EV constraints. PV generation alone is not
  available surplus. Tariffs and forecasts need valid timestamps and horizons.

Use HA's `Australia/Hobart` timezone and timezone-aware local deadlines. Generate
each day's 07:00/peak deadlines from local calendar dates and the configured
tariff schedule, then compare/store UTC instants. Do not advance deadlines by
fixed 24-hour UTC offsets across DST. Test both DST transitions, weekends,
missing/duplicated local times, and tariffs that may use fixed standard time.
Deduplicate decisions by local date/deadline and optimiser publication ID.

## Thermal model and uncertainty

The tank is **315 L**, element **3 kW**, and the sensor is at the bottom. A bottom
reading is not a whole-tank average or direct usable-hot-water volume. Retain
the manufacturer's approximately 8°C thermostat hysteresis; a setpoint request
does not guarantee immediate heating or element energisation.

For a hypothetical uniformly mixed full tank only,
`E ≈ 315 × 4.186 × ΔT / 3600 = 0.366 × ΔT kWh`, with ideal heating time `E/3 h`.
For example, uniform 40→65°C is about 9.2 kWh/3.1 h before losses. This is a
design calculation, not a measured tank-energy sensor or permission to treat
bottom temperature as average. Calibrate a stratification/reserve model later
against supervised draw/heating observations and real electrical measurements;
retain uncertainty margins, cold-water temperature, losses and demand forecast.

A morning bottom reading around 40°C is a comfort/readiness indicator, not an
acceptable long-term storage setpoint. Manufacturer storage guidance, manual
range, antibacterial cycles and thermostat limits remain binding. Do not use an
unverified status bit to estimate power, energy, remaining heat or safe hygiene.

## Proposed control state machine

1. **Native / observing:** no HA control ownership. Verify real temperature,
   vendor mode, device availability, cloud health and meter/forecast/tariff ages.
2. **Readiness evaluation:** request a rate-limited read only when a new scheduled
   decision genuinely needs freshness. Wait a bounded time for a newer timestamp;
   no action on timeout, backoff, lockout or stale data. Solar changes update the
   local plan and cannot create a cloud-call loop. A denied refresh does not
   authorise bypassing spacing or widening a freshness bound.
3. **Proposed acquisition:** only after separate command approval, capture a
   verified native baseline and ownership record. Ensure no active hygiene cycle
   or conflicting native/manual intervention. Validate current mode and allowed
   setpoint range; legacy bridge 20–75°C limits are not Thermann qualification.
4. **One command:** issue at most one approved mode/setpoint request for that
   decision. Record immutable intent; do not resend a write automatically on
   timeout, ambiguity or HTTP success without state confirmation.
5. **Bounded confirmation:** retain observed state, with at most a separately
   approved small number of spaced reads in a finite confirmation window. Count
   each read/auth refresh against local usage. Never publish requested state as
   actual state. Unconfirmed writes end the cycle and require review/reconciliation.
6. **Native handback:** restore verified native Schedule only through a separately
   tested route and confirmed readback; a Schedule label alone does not prove
   the stored program or hygiene protections are intact. Native user changes are
   authoritative. Never clear ownership merely because a restoration was sent.

There is no verified unconditional element-on/boost API. `/manual` changes mode
and temperature together. `/auto` conventionally produces Cmd 17 but schedule
contents are not exposed by an understood read schema. Off is not an approved
heating-demand switch; do not assume it preserves all safeguards on this API and
firmware. No unverified `/schedule`, boost or energy endpoint may be invented.

## Outages and fallback — approval blocker

A saved schedule is not an automatic fallback while the heater is in Manual or
Off. HA cannot guarantee remote Schedule restoration when MQTT/cloud is down.
Until native behavior or an approved local failsafe is demonstrated, unattended
control ownership is **NO-GO**. On stale temperature, failed meter/forecast data,
cloud rejection or command ambiguity, stop issuing new writes, retain ownership
evidence and alert the owner. Do not repeatedly issue Off or handback commands.
The device's own thermostat/hygiene controls remain powered and authoritative.

Before automation, qualify the native fallback schedule through genuine HA/MQTT/
cloud outages under supervision, or keep native Schedule as the controlling
mode. Optimisation cannot promise both comfort and safe fallback without that
evidence. Do not silently relax safety gates to make the optimiser produce actions.

## Supervised qualification sequence — not executed

1. Qualify read-only monitoring, units, bottom-sensor behavior, quota/cooldown and
   timestamps at the selected background/demand cadence. Establish electrical
   metering and net-export sign; no heater writes.
2. With explicit approval for each step, test Manual/setpoint, Schedule/Auto,
   Eco and separate power behavior individually, including side effects and
   manufacturer hygiene-cycle interference. Preserve and verify fallback program.
   Do not start with Off or assume Schedule's native HA mode label is available.
3. Test one bounded command-confirmation cycle and fully confirmed native
   restoration, then interruptions, duplicate optimiser events, unexpected native
   mode changes and lost confirmation. No automatic repeated heater writes.
4. Replay morning reserve/solar/off-peak/evening scenarios offline, including
   poor forecasts, cold starts, depleted reserve, weekends/DST, tariff changes,
   insufficient import capacity and multiple missed decisions.
5. Only after owner acceptance, stage one limited comfort-first control window
   with a documented rollback and supervised verified handback. Unattended
   EMHASS optimisation is a later approval, not implied by a read-only PR.
