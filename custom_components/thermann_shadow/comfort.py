"""Fresh pre-peak warnings; legacy morning helper retained for historical replays."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def pre_peak_availability(
    now,
    reading,
    observed_at,
    next_peak,
    *,
    threshold=35,
    lead_minutes=30,
    max_age_minutes=45,
    boot=None,
):
    """Fresh bottom-probe warning for either configured peak, never a heat target."""
    result = {
        "state": "not_due",
        "threshold_c": threshold,
        "reading_c": reading,
        "observed_at": observed_at.isoformat() if observed_at else None,
        "next_peak": next_peak.isoformat() if next_peak else None,
        "whole_tank_temperature_known": False,
    }
    if next_peak is None or not timedelta(0) <= next_peak - now <= timedelta(minutes=lead_minutes):
        return result
    if (
        reading is None
        or not 0 <= reading <= 100
        or observed_at is None
        or not timedelta(0) <= now - observed_at <= timedelta(minutes=max_age_minutes)
        or (boot is not None and observed_at < boot)
        or observed_at < next_peak - timedelta(minutes=lead_minutes)
    ):
        result["state"] = "unverified"
    else:
        result["state"] = "low" if reading < threshold else "latest_probe_above_warning"
    return result


def morning_availability(now, reading, observed_at, time_zone, max_age_minutes=45):
    """Retired diagnostic helper; production uses pre_peak_availability only."""
    local = now.astimezone(ZoneInfo(time_zone))
    preferred = datetime.combine(local.date(), time(6), ZoneInfo(time_zone))
    hard = datetime.combine(local.date(), time(7), ZoneInfo(time_zone))
    result = {
        "state": "not_due",
        "preferred_c": 45,
        "minimum_c": 42,
        "preferred_at": preferred.isoformat(),
        "minimum_at": hard.isoformat(),
        "observed_at": observed_at.isoformat() if observed_at else None,
        "reading_c": reading,
        "proves_deadline_met": False,
    }
    if not time(5) <= local.time().replace(tzinfo=None) < time(9):
        return result
    fresh = (
        reading is not None
        and observed_at is not None
        and timedelta(0) <= now - observed_at <= timedelta(minutes=max_age_minutes)
    )
    if not fresh:
        result["state"] = "unverified"
    elif now >= hard and observed_at >= hard and reading < 42:
        result["state"] = "minimum_shortfall_observed"
    elif reading < (42 if now >= hard else 45):
        result["state"] = "at_risk"
    else:
        result["state"] = "latest_probe_above_requirement"
    return result
