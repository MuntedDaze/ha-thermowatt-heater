"""Read-only recommendation for a future bounded adaptive Thermann cloud poll.

This module NEVER schedules a cloud request. The bridge continues its existing
30-minute cadence. Recommendations are diagnostics for shadow comparison only.
Any future actuation requires separately approved bridge/HA design and testing.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite

from .model import TANK_KWH_PER_C

STABLE_MAX_MINUTES = 90
HEATING_MAX_MINUTES = 60
UNCERTAIN_MAX_MINUTES = 30
BOUNDARY_MAX_MINUTES = 15
NEAR_TARGET_MINUTES = 90


def recommend_poll(
    now: datetime,
    poll_at: datetime | None,
    *,
    mode: str | None,
    temperature_c: float | None,
    target_c: float | None,
    heater_power_kw: float | None,
    heater_meter_configured: bool,
    next_tariff_at: datetime | None,
    cloud_health: str | None,
    owner_override: bool = False,
) -> dict:
    """Return a non-actuating next-status recommendation and its rationale.

    Unverified token inactivity limits are a rollout blocker, not an excuse
    to issue immediate refreshes. A bridge in backoff must own its retries.
    """
    result = {
        "shadow_only": True,
        "recommended_interval_minutes": None,
        "recommended_due_at": None,
        "estimated_heating_minutes": None,
        "reason": "unknown",
    }
    if cloud_health != "ok":
        result["reason"] = "cloud_unavailable_bridge_controls_retry"
        return result

    interval = UNCERTAIN_MAX_MINUTES
    reason = "uncertain_or_unmetered"
    if (
        heater_meter_configured
        and heater_power_kw is not None
        and mode in {"Off", "Manual"}
        and temperature_c is not None
        and target_c is not None
        and all(isfinite(v) for v in (heater_power_kw, temperature_c, target_c))
    ):
        if mode == "Manual" and heater_power_kw > 2.0:
            # An optimistic fully-mixed physical estimate, NOT a validated
            # completion guarantee: tank bottom stratification and draws matter.
            minutes = max(0.0, target_c - temperature_c) * TANK_KWH_PER_C / heater_power_kw * 60
            result["estimated_heating_minutes"] = round(minutes)
            interval = HEATING_MAX_MINUTES if minutes > NEAR_TARGET_MINUTES else 30
            reason = "metered_heating_far_from_target" if interval == 60 else "metered_heating_near_target"
        else:
            interval, reason = STABLE_MAX_MINUTES, "verified_element_idle"
    if owner_override:
        interval, reason = min(interval, UNCERTAIN_MAX_MINUTES), "owner_override"
    if next_tariff_at is not None:
        remaining = (next_tariff_at - now).total_seconds() / 60
        if 0 <= remaining <= 30:
            interval, reason = min(interval, BOUNDARY_MAX_MINUTES), "tariff_boundary_approaching"
    if poll_at is None:
        due = now
        reason = "no_prior_status"
    else:
        due = max(now, poll_at + timedelta(minutes=interval))
    result.update(
        recommended_interval_minutes=interval,
        recommended_due_at=due.isoformat(),
        reason=reason,
    )
    return result
