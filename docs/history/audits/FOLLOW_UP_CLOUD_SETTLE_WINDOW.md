# Follow-up proposal: cloud settle window for re-inspection

Status: **proposal only, not implemented, needs owner approval**. It changes
automatic-control behaviour, so it belongs in its own PR, not PR #43.

## Problem

After a change in the Thermann app, the vendor cloud can return the previous
mode for 2 to 63 s (owner test T3c; see command confirmation in the bridge
[DOCS](../../../thermowatt-heater/DOCS.md)). The controller
re-inspects the heater after Enable, Resume, fault acknowledgement, HA restart
and guest/holiday transitions. It accepts the first read whose `poll_at` is
later than `inspect_after`. If that read comes within the lag (for example an
on-demand refresh served just after the owner changed the app and then enabled
control), the controller classifies the stale state. It can then enter owner
override and stop heating until the next Resume.

The audit showed this concretely. A prototype immediate read on Resume, run in
`tests/test_pre_review_failure_replay.py`, captured a stale Manual 55 after the
owner chose Off. That caused an override lock-in and about 18 kWh of unserved
draw. The prototype was removed. Today the hazard is narrower but real for
activation when on-demand refresh is enabled.

## Proposed design

1. Add a constant `REINSPECT_SETTLE_SECONDS = 90`. That is the 63 s measured
   maximum plus a margin. It is not a setting.
2. In `Controller._fresh_after_inspection`, a read is fresh for inspection only
   if `poll_at > inspect_after + 90 s`. Ordinary steady-state freshness
   (`inspect_after is None`) is unchanged.
3. A controller refresh request linked to re-inspection is sent no earlier
   than `inspect_after + 90 s`, once. It stays subject to the bridge's 300 s
   spacing and every bridge guard. No queue, no new client or scheduler, and no
   change to the bridge.
4. While settling, the reason is `waiting_for_cloud_to_settle`. The dashboard
   explains it as "Waiting briefly for the Thermann cloud to catch up".
5. Smart plan selection while inspecting is not changed by this proposal.
   A review should confirm that no quiet plan can be issued before
   classification.
6. `inspect_after` is already persisted, so a restart during the window keeps
   the window. Nothing new is stored.

What it does not change: command prechecks (exact prior), confirmation reads
and their bounded follow-ups, peak-OFF, Hold, fault lock, owner-override
detection in steady state, the 45/62/70 °C roles, authentication and request
limits.

Cost: if the owner did not change the app, classification after Enable or
Resume can be at most 90 s later than today. In practice it usually is not,
because the next scheduled read is normally later than that anyway.

## Test requirements

- The failure replay with a Resume-time refresh no longer produces owner
  override or unserved draw. The published replay artifacts are unchanged, or
  any change is explained.
- Unit tests: a read at `inspect_after + 89 s` is ignored and one at `+91 s`
  classifies. A stale Manual 55 inside the window is never classified. A
  genuine app change seen after the window is still detected as an override.
- Request tests: at most one refresh per re-inspection, never before the
  window, and repeated Enable/Resume within 300 s does not add reads. HTTP
  counts in the seasonal and week replays do not rise.
- Restart: HA restarts inside the window, and the window and `inspect_after`
  survive. No command is replayed.
- Every re-inspection entry point is covered: enable, resume, acknowledge,
  restart, guest start/cancel/end and holiday.
- Use the Home Assistant whole-second timestamps and fractional clocks from
  `tests/test_smart_plan_acceptance_1_4_1.py`.
- All existing suites, static checks, HA Core and container CI pass.
