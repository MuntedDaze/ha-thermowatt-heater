"""Planner -> controller boundary. Pure functions; never publishes anything.

``desire_from_advice`` turns the 0.4.0 planner's advice (stabilised economic
decision, best plan blocks, readiness) into ONE desired action for the coming
command interval. A decision is rounded to the nearest command slot (half the
latency reserve) instead of chasing every minute, which keeps switching rare.

``SessionTemperature`` guards against the bottom-sensor overshoot seen in T1
(11 Nov 2026): ~0.19 kWh of heating moved the reading 55 -> 62 °C. During and
shortly after heating the planning temperature is capped at the start reading
plus the delivered energy, so a local hot zone is never mistaken for stored heat.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .advisor import GATE_CODES
from .controller import Desire
from .model import ELEMENT_KW, TANK_KWH_PER_C

HEAT_CODES = {
    "heat_now_cheapest",
    "heat_now_saving_too_small",
    "heat_now_comfort_fallback",
    "insufficient_time",
}
PEAK_GUARD_MARGIN = timedelta(minutes=5)
OVERSHOOT_ALLOWANCE_C = 1.0
SESSION_SETTLE = timedelta(minutes=90)


COMFORT_CODES = {"heat_now_comfort_fallback", "insufficient_time"}
MORNING_FAILSAFE_MARGIN_C = 5.0
MORNING_FAILSAFE_HOURS = 4.0


def holiday_desire(
    now: datetime,
    window: tuple[datetime, datetime],
    advice,
    permitted: bool,
    latency_minutes: float,
    next_peak_start: datetime | None,
    element_state: str = "unknown",
) -> Desire:
    """Away (0.7.0): parked (Thermann OFF keeps its antibacterial and frost
    protection) until the last 24 hours; then the planner prepares only the
    return goal with the planner-only rules (no economic standby, no morning
    goals). Owner app changes still pause control as usual."""
    from .goals import HOLIDAY_PREPARATION

    if now < window[1] - HOLIDAY_PREPARATION:
        return Desire("park", "holiday_away")
    return _planner_only_desire(
        now, advice, permitted, latency_minutes, next_peak_start, element_state
    )


def morning_failsafe_window(now: datetime, settings, tariffs):
    """(opens, hard deadline, threshold) of the next morning goal: the hours
    before the hard deadline in which an unavailable planner or meter must
    not leave the heater parked (off-peak hours on every Aurora 93 day)."""
    from .goals import upcoming_goals

    for goal in upcoming_goals(now, settings, tariffs):
        if goal.kind == "morning" and goal.hard_deadline is not None:
            hard = goal.hard_deadline
            return hard - timedelta(hours=MORNING_FAILSAFE_HOURS), hard, goal.target_c
    return None


def desire_from_advice(
    now: datetime,
    advice,
    permitted: bool,
    latency_minutes: float,
    next_peak_start: datetime | None,
    element_state: str = "unknown",
    *,
    standby=None,
    economics=None,
    reading: float | None = None,
    morning_window: tuple[datetime, datetime, float] | None = None,
) -> Desire:
    """ONE desired action for the coming command interval.

    0.7.0 (with ``standby``, the production path) separates heating PERMISSION
    from heating NEED. Comfort and planned blocks permit as before. Otherwise
    Manual 70 °C stays permitted, or is granted, while heating now would be
    economical (meter-priced, see permission.py), and the heater is parked
    when it no longer is, including at a peak start unless solar justifies
    staying on. Afternoon storage never buys peak-grid heat; a morning comfort
    heat continues into a morning peak (hot water before savings).

    Without ``standby`` the 0.6.x planner-only rules apply.
    """
    if standby is None:
        return _planner_only_desire(
            now, advice, permitted, latency_minutes, next_peak_start, element_state
        )
    half = timedelta(minutes=max(1.0, latency_minutes) / 2)
    peak_soon = (
        next_peak_start is not None
        and now <= next_peak_start <= now + timedelta(minutes=latency_minutes) + PEAK_GUARD_MARGIN
    )
    if advice is None or advice.assessment is None or advice.economic_code in GATE_CODES:
        reason = (advice.economic_code if advice is not None else None) or "planner_not_ready"
        if morning_window is not None:
            # Meter or planner unavailable before the morning hard deadline:
            # permit (off-peak hours) rather than risk cold showers.
            opens, hard, threshold = morning_window
            if opens <= now < hard and (
                reading is None or reading < threshold + MORNING_FAILSAFE_MARGIN_C
            ):
                return Desire(
                    "permit",
                    "morning_failsafe_planner_unavailable",
                    planner_ok=False,
                    comfort=True,
                )
        if permitted and peak_soon:
            return Desire(
                "park", "peak_starting_planner_unavailable", planner_ok=False, urgent=True
            )
        return Desire("hold", reason, planner_ok=False)
    code = advice.economic_code or advice.code
    result = advice.assessment
    best = result.plans.get("best_overall")
    blocks = [(a, b) for a, b in (best.blocks if best else []) if b > now]
    upcoming = [a for a, _ in blocks if a > now]
    current = next(((a, b) for a, b in blocks if a - half <= now < b), None)
    comfort_risk = next(
        (kind for kind, item in advice.readiness.items() if item.get("status") == "unachievable"),
        None,
    )
    next_start = upcoming[0] if upcoming and not current else None
    next_stop = current[1] if current else (blocks[0][1] if blocks else None)
    common = {"next_start": next_start, "next_stop": next_stop, "comfort_risk": comfort_risk}
    next_goal = advice.goals[0].kind if advice.goals else None

    def economic(reason_prefix: str | None = None) -> Desire:
        action, reason, urgent = standby.decide(now, economics, permitted, peak_soon)
        if action == "permit":
            return Desire("permit", reason, standby=True, **common)
        if action == "park":
            return Desire("park", reason_prefix or reason, urgent=urgent, **common)
        return Desire("hold", reason, **common)

    # Morning comfort comes first, including into a morning peak.
    if morning_window is not None and reading is not None and next_goal == "morning":
        opens, hard, threshold = morning_window
        if opens <= now < hard and reading < threshold + MORNING_FAILSAFE_MARGIN_C:
            # Real morning hot water before savings: below the threshold,
            # permit; once heating, keep going until a 5 °C margin covers
            # standing loss and sensor stratification up to the hard deadline
            # (these hours are off-peak on every Aurora 93 day).
            if permitted or reading < threshold:
                return Desire("permit", "morning_comfort_margin", comfort=True, **common)
    if code in COMFORT_CODES and next_goal == "morning":
        return Desire("permit", f"morning_comfort_{code}", comfort=True, **common)
    # Before a peak (decided ahead: commands take about a minute): afternoon
    # storage never buys peak-grid heat, whether or not Manual is on now;
    # only solar can justify permission across the peak start.
    if peak_soon:
        return economic()
    if code in COMFORT_CODES:
        return Desire("permit", f"afternoon_storage_{code}", comfort=True, **common)
    if current is not None:
        ending = permitted and current[1] - now <= half
        following = next((a for a in upcoming if a >= current[1]), None)
        if not ending or (following is not None and following - current[1] <= half):
            return Desire("permit", f"planned_block_{code}", **common)
        return economic()
    if code in HEAT_CODES and best is None:
        return Desire("permit", code, **common)
    if code == "wait_cheaper_later":
        # The planner found the NEEDED heat cheaper later; only strong current
        # economics (e.g. solar now) keeps permission meanwhile.
        desire = economic()
        if desire.action == "permit" and not (economics and economics.grant):
            return Desire("park", "waiting_for_cheaper_heating", **common)
        return desire
    # Nothing needed now (goals met, thermostat satisfied, flexible): permission
    # follows economics only.
    return economic()


def _planner_only_desire(
    now: datetime,
    advice,
    permitted: bool,
    latency_minutes: float,
    next_peak_start: datetime | None,
    element_state: str = "unknown",
) -> Desire:
    """0.6.x rules: no meter economics (kept for planner-only callers)."""
    half = timedelta(minutes=max(1.0, latency_minutes) / 2)
    peak_soon = (
        next_peak_start is not None
        and now <= next_peak_start <= now + timedelta(minutes=latency_minutes) + PEAK_GUARD_MARGIN
    )
    if advice is None or advice.assessment is None or advice.economic_code in GATE_CODES:
        reason = (advice.economic_code if advice is not None else None) or "planner_not_ready"
        if permitted and peak_soon:
            return Desire("park", "peak_starting_planner_unavailable", planner_ok=False)
        return Desire("hold", reason, planner_ok=False)
    code = advice.economic_code or advice.code
    result = advice.assessment
    best = result.plans.get("best_overall")
    blocks = [(a, b) for a, b in (best.blocks if best else []) if b > now]
    upcoming = [a for a, _ in blocks if a > now]
    current = next(((a, b) for a, b in blocks if a - half <= now < b), None)
    comfort_risk = next(
        (kind for kind, item in advice.readiness.items() if item.get("status") == "unachievable"),
        None,
    )
    next_start = upcoming[0] if upcoming and not current else None
    next_stop = current[1] if current else (blocks[0][1] if blocks else None)
    common = {"next_start": next_start, "next_stop": next_stop, "comfort_risk": comfort_risk}
    # Last command slot before a peak: staying in Manual across the peak start
    # only risks a peak-price reheat once the reading falls to 62 °C. Park unless
    # the element is heating right now for comfort (replay of 10 Nov: polls at
    # :04/:34 left Manual on until 17:04 under "insufficient time").
    if permitted and peak_soon and element_state != "on":
        return Desire("park", "peak_starting_element_not_heating", **common)
    if code == "heat_now_comfort_fallback":
        return Desire("permit", "comfort_fallback_latest_start", comfort=True, **common)
    if code == "insufficient_time":
        return Desire(
            "permit", "insufficient_time_heat_as_much_as_possible", comfort=True, **common
        )
    if permitted and peak_soon:
        return Desire("park", "peak_starting", **common)
    if permitted and advice.satisfied:
        return Desire("park", "native_thermostat_satisfied", **common)
    if code == "no_heating_needed":
        return Desire("park", "no_heating_needed", **common)
    if current is not None:
        if permitted and current[1] - now <= half:
            following = next((a for a in upcoming if a >= current[1]), None)
            if following is None or following - current[1] > half:
                return Desire("park", "planned_block_ending", **common)
        return Desire("permit", f"planned_block_{code}", **common)
    if code in HEAT_CODES and best is None:
        return Desire("permit", code, **common)
    return Desire("park", f"waiting_{code}", **common)


@dataclass
class SessionTemperature:
    start_reading: float | None = None
    delivered_kwh: float = 0.0
    last_at: datetime | None = None
    off_at: datetime | None = None

    def update(self, now: datetime, raw: float | None, element: str) -> float | None:
        if raw is None:
            return None
        if element == "on":
            if self.start_reading is None or (self.off_at and now - self.off_at > SESSION_SETTLE):
                self.start_reading, self.delivered_kwh, self.off_at = raw, 0.0, None
            elif self.last_at is not None:
                step = min(timedelta(minutes=2), max(timedelta(0), now - self.last_at))
                self.delivered_kwh += ELEMENT_KW * step.total_seconds() / 3600
            self.off_at = None
            self.last_at = now
        elif self.start_reading is not None:
            self.off_at = self.off_at or now
            self.last_at = now
            if now - self.off_at > SESSION_SETTLE or raw < self.start_reading:
                self.start_reading, self.delivered_kwh, self.off_at = None, 0.0, None
        if self.start_reading is None:
            return raw
        cap = self.start_reading + self.delivered_kwh / TANK_KWH_PER_C + OVERSHOOT_ALLOWANCE_C
        return round(min(raw, cap), 2)

    def summary(self) -> dict:
        return {
            "session_start_reading_c": self.start_reading,
            "session_delivered_kwh": round(self.delivered_kwh, 3),
            "element_off_since": self.off_at.isoformat() if self.off_at else None,
            "basis": "bottom sensor capped at start + delivered energy for 90 min after heating (T1 overshoot)",
        }
