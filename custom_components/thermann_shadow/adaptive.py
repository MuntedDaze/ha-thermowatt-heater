"""Smart polling plan (v3). Pure; publishing a plan never requests HTTP itself.

One polling configuration (owner decision D2, 0.18.0): the Thermann Hot Water
app's option selects Smart, and the controller sends these expiring plans only
when the app reports Smart (``Executor._bridge_smart``). Without a valid plan the
app uses its automatic fixed 30-minute schedule: at startup, after communication
problems, for a missing or rejected plan, or after a scheduler failure. A plan
never makes a temperature fresh and never authorises a command; command
freshness and request protections stay in the app and the controller gates.
"""

from datetime import datetime
import math

QUIET_OVERNIGHT_SECONDS = 28800  # 8 h: confirmed quiet baseline/OFF overnight
QUIET_DAY_SECONDS = 5400  # 90 min: confirmed quiet baseline/OFF by day
SLOT_SECONDS = 1800  # half-hour clock alignment for temperature-relevant reads


def smart_plan(
    now,
    status_at,
    *,
    stable_state=None,
    temperature_valid=False,
    overnight=False,
    decision_at=None,
    completion_at=None,
):
    """Next read for the app's Smart scheduler; its 180 s lease never extends.

    Quiet (confirmed baseline/OFF): up to 8 h overnight or 90 min by day, or an
    earlier useful event. Otherwise the next half-hour slot (15-30 min), or
    15 min when the temperature is unknown. A dead controller loses the lease
    and the app returns to its fixed 30-minute schedule.
    """
    if status_at is None:
        return None
    age = (now - status_at).total_seconds()
    if not 0 <= age <= QUIET_OVERNIGHT_SECONDS:
        return None
    owner = QUIET_OVERNIGHT_SECONDS if overnight else QUIET_DAY_SECONDS
    quiet = stable_state in {"baseline", "off"}
    next_slot = (math.floor(status_at.timestamp() / SLOT_SECONDS) + 1) * SLOT_SECONDS
    delay = owner if quiet else min(1800, max(900, next_slot - status_at.timestamp()))
    reason = "stable_" + stable_state if quiet else "required_temperature"
    if not quiet and not temperature_valid:
        delay, reason = 900, "uncertain"
    for when in (decision_at, completion_at):
        if isinstance(when, datetime) and when >= now:
            candidate = (when - status_at).total_seconds()
            if candidate < delay:
                delay, reason = (
                    max(900, candidate),
                    "quiet_before_decision" if quiet and candidate > 2400 else "before_decision",
                )
    return {
        "version": 3,
        "status_at": status_at.timestamp(),
        "issued_at": now.timestamp(),
        "delay_seconds": math.floor(delay),
        "reason": reason,
        "owner_check_seconds": owner,
        "polling_mode": "smart",
    }
