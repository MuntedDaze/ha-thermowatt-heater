"""Pure bounded plan creation; publishing a plan never requests HTTP itself."""

from datetime import datetime, timedelta
import math


def make_plan(
    now,
    status_at,
    *,
    heating,
    has_ct,
    temperature_valid,
    decision_at=None,
    completion_at=None,
    status_max_minutes=45,
):
    if status_at is None or not 0 <= (now - status_at).total_seconds() <= 5400:
        return None
    # Stay inside the existing temperature freshness limit, with five minutes
    # to recover. Never infer measured heating from nominal power/cloud mode.
    cap = min(40 * 60, max(15 * 60, (status_max_minutes - 5) * 60))
    delay = cap if has_ct else min(cap, 30 * 60)
    reason = "heating" if heating is True else "stable" if has_ct else "ct_free"
    if not temperature_valid:
        delay, reason = 15 * 60, "uncertain"
    for when, why in ((decision_at, "before_decision"), (completion_at, "near_completion")):
        if isinstance(when, datetime):
            candidate = (when - timedelta(minutes=10) - status_at).total_seconds()
            if candidate < delay:
                delay, reason = max(900, candidate), why
    return {
        "version": 1,
        "status_at": status_at.timestamp(),
        "issued_at": now.timestamp(),
        "delay_seconds": math.floor(delay),
        "reason": reason,
    }
