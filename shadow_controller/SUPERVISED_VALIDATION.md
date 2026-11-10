# Later supervised qualification — design only, not executed

Phase 2A contains no command implementation. These are prerequisites for a
separate owner-approved test plan, not permission to run it now.

1. Keep native Schedule as owner. Confirm the physical model/firmware and matching
   manufacturer guidance. Independently check exact weekly windows, 70°C target,
   10°C T-Comfort, device time/DST, manufacturer hygiene settings and any plumbing
   temperature protections. Preserve the programme. Never infer protection from
   a generic API range, a status bit or the word Off.
2. Verify grid sign/units with a known non-heater load under owner supervision;
   distinguish PV, house demand, export and controlled/battery/EV loads. Establish
   a credible element-power observation method; a coincident whole-house 3 kW
   change alone is not confirmed element feedback. Do not modify hardware or
   electrical protections to acquire this evidence.
3. Replay useful days before writes: poor solar, depleted morning reserve,
   delayed forecast, tariff changes, DST/weekends, missed polls, quota locks,
   Internet/MQTT/HA outages and manual changes. Qualify client/device sample lag.
   A shadow “heat now” never implies actual energisation or an executable plan.
4. Only with a new explicit approval, plan one bounded Manual/setpoint experiment
   inside a supervised recovery window. Require fresh observed state, OK cloud,
   available usage headroom, no active conflicting hygiene/native intervention,
   verified device-specific limits and a tested independent recovery method.
   Stay physically supervised. Preserve baseline evidence and record one immutable
   intent. No repeated writes on timeout/ambiguous acceptance; no Off test or
   “Off/Auto switch” shortcut. Bridge command enablement would require separate
   review, not an option in this component.
5. A future confirmation design must budget each GET, refresh, GET replay and
   write. Any pre-read and bounded post-read must respect bridge cooldowns and
   quota locks; never proactively refresh tokens to make a trial proceed. Current
   30-minute background data alone does not satisfy the bridge's tighter command
   freshness check. A separately reviewed finite read/write plan is required.
6. Qualify Schedule restoration separately, by observed vendor mode plus unchanged
   app programme, target/T-Comfort and later autonomous behaviour. Cmd=17 alone
   cannot prove a saved weekly programme. A higher T-Comfort is a separate
   Schedule-only fallback trade-off: better minimum reserve versus possible
   peak imports. Do not use it as a Manual/Off escape route. Keep 10°C unchanged
   throughout Phase 2A. Do not repeatedly send restoration commands on failure.
7. Demonstrate fallback/recovery when HA, MQTT, Internet or the vendor API fails.
   A saved schedule does not rescue a heater left in Manual. App access may fail
   with the same cloud, so it is not automatically an independent recovery route.
   If safe handback cannot be independently assured, abandon temporary control
   and leave Schedule in charge. Do not run unattended experiments to find out.

EMHASS is a later optimiser adapter, not a safety layer. It may eventually consume
qualified reserve uncertainty, net-export/load forecasts and actual prices, but
must submit bounded proposals to a separately qualified controller with explicit
ownership/confirmation/handback. It must not publish directly to heater commands.
No unattended control until reliable native recovery has been demonstrated.
