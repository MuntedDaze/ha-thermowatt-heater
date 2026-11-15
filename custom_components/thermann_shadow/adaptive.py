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


def event_plan(
    now,
    status_at,
    *,
    stable_state=None,
    temperature_valid=False,
    decision_at=None,
    owner_check_minutes=60,
    status_max_minutes=45,
):
    """Separate temperature evidence from an explicitly bounded owner check.

    A quiet lease holds a confirmed thermostat setting, never a temperature or
    physical ON/OFF inference. Exact-prior and confirmation remain bridge-owned.
    Decision observations align with the actual decision, not ten minutes before
    a command whose prerequisite expires in sixty seconds.
    """
    if status_at is None or not 0 <= (now - status_at).total_seconds() <= 5400:
        return None
    if not 30 <= owner_check_minutes <= 90:
        return None
    owner_limit = int(owner_check_minutes * 60)
    if stable_state in ("baseline", "off"):
        delay, reason = owner_limit, "stable_" + stable_state
    else:
        cap = min(owner_limit, 2400, max(900, (status_max_minutes - 5) * 60))
        # During consequential temperature planning, rejoin the established
        # half-hour observation grid. Arbitrary 40-minute phases delayed cloud
        # outage discovery near peak in the week replay. Recent confirmation
        # reads are reused; minimum spacing can briefly offset a slot.
        next_slot = (math.floor(status_at.timestamp() / 1800) + 1) * 1800
        delay = min(cap, max(900, next_slot - status_at.timestamp()))
        reason = "required_temperature"
        if not temperature_valid:
            delay, reason = 900, "uncertain"
    if isinstance(decision_at, datetime):
        candidate = (decision_at - status_at).total_seconds()
        if candidate < delay:
            delay = max(900, candidate)
            if delay <= 2400:
                reason = "before_decision"
    return {
        "version": 2,
        "status_at": status_at.timestamp(),
        "issued_at": now.timestamp(),
        "delay_seconds": math.floor(delay),
        "reason": reason,
        "owner_check_seconds": owner_limit,
    }
