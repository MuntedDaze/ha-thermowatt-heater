"""Planner -> controller boundary. Pure functions; never publishes anything.

``desire_from_advice`` turns the 0.4.0 planner's advice (stabilised economic
decision, best plan blocks, readiness) into ONE desired action for the coming
command interval. Commands are poll-aligned, so a decision is rounded to the
nearest command slot (half the poll interval) instead of chasing every minute.

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


def desire_from_advice(
    now: datetime,
    advice,
    permitted: bool,
    latency_minutes: float,
    next_peak_start: datetime | None,
    element_state: str = "unknown",
) -> Desire:
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
        return Desire("permit", "comfort_fallback_latest_start", **common)
    if code == "insufficient_time":
        return Desire("permit", "insufficient_time_heat_as_much_as_possible", **common)
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
