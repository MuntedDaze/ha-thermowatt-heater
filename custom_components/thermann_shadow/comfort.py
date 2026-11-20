"""Low-water notification before the evening peak (owner decision D1, 20 Nov 2026).

A notification only: never a heating target, heating permission or change to the
heater's native protections. There is no morning check: the 0.7.0 morning
reserve (45 C by 06:00 / 42 C by 07:00) is cancelled (docs/OPERATING_POLICY.md).
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

# A peak starting at or after this household-local hour is the evening peak
# (the same rule simple_policy uses for weekday storage deadlines).
EVENING_PEAK_FROM_HOUR = 12


def evening_peak(next_peak, time_zone):
    """``next_peak`` if it is an evening peak in household time, else None."""
    if next_peak is None:
        return None
    return (
        next_peak
        if next_peak.astimezone(ZoneInfo(time_zone)).hour >= EVENING_PEAK_FROM_HOUR
        else None
    )


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
    """Fresh bottom-probe warning before ``next_peak`` (the caller passes only an
    evening peak), never a heat target."""
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
