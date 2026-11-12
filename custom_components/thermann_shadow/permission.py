"""Economic heating PERMISSION, kept separate from physical heating. Pure logic.

Manual 70 °C only PERMITS heating: Thermann's own thermostat decides when the
element runs (for example straight after hot water is used). Leaving the
permission on costs nothing while the element is idle. What matters is the
price of the energy the element WOULD draw if it switched on now, compared with
the cheapest realistic way of supplying the same heat later, before it is
needed. This module makes that comparison from LOCAL readings only (GoodWe /
HK1000 meter, EMHASS forecast slots); it never causes a cloud request.

Solar available to the element is measured EXCLUDING the element itself: the
advisor's base load removes 3 kW while the element is detected on. So the
element consuming solar that was being exported does not look like lost solar,
and permission does not oscillate because of the element's own load.

Stability:
- rolling 10-minute median of the surplus (passing clouds, kettle spikes);
- a cautious surplus (the lower of median and now, minus headroom) to GRANT
  permission, the typical (median) surplus to WITHDRAW it (hysteresis by data);
- a price margin: grant when no worse than the alternative, withdraw only when
  clearly worse;
- sustained-condition timers: 10 minutes normally, 5 minutes during a peak.

Commands still go through every controller gate (dwell, daily command budget,
cloud health). Cloud commands take about a minute and can fail, so nothing
here promises zero grid import.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from .advisor import GATE_CODES
from .model import ELEMENT_KW, tariff_at

ROLLING = timedelta(minutes=10)
ECONOMIC_HOLD = timedelta(minutes=10)
PEAK_HOLD = timedelta(minutes=5)
NEAR_TERM = timedelta(minutes=30)  # alternatives start after the measured horizon
ALTERNATIVE_HOURS = 1.0  # the cheapest HOUR of alternatives, never one lucky slot
PERMIT_TOLERANCE = 0.005  # $/kWh: grant when not worse than the alternative
PARK_MARGIN = 0.03  # $/kWh: withdraw only when clearly worse
STRONG_SOLAR_SHARE = 0.5  # half the element's power from solar or more
HEADROOM_KW = 0.3


@dataclass
class Economics:
    at: str
    rate: float  # $/kWh grid price that applies to the decision
    peak: bool
    feed_in: float
    surplus_kw: float | None  # rolling median, element excluded
    cautious_surplus_kw: float | None
    solar_share: float | None  # of the element's 3 kW, typical
    cost_kwh: float | None  # typical price per kWh if the element ran now
    cautious_cost_kwh: float | None  # price with the cautious surplus
    alternative_kwh: float | None  # cheapest hour of alternatives before the need
    alternative_basis: str
    grant: bool  # permission would be economical now
    withdraw: bool  # permission is clearly uneconomical now

    def summary(self) -> dict:
        data = asdict(self)
        for key in ("surplus_kw", "cautious_surplus_kw", "solar_share"):
            if data[key] is not None:
                data[key] = round(data[key], 3)
        for key in ("cost_kwh", "cautious_cost_kwh", "alternative_kwh"):
            if data[key] is not None:
                data[key] = round(data[key], 4)
        return data


def blended_cost(surplus_kw: float, rate: float, feed_in: float) -> tuple[float, float]:
    """(solar share, $/kWh) for the 3 kW element with `surplus_kw` available."""
    share = min(1.0, max(0.0, surplus_kw / ELEMENT_KW))
    return share, share * feed_in + (1 - share) * rate


def alternative_cost(now: datetime, slots, goals, feed_in: float) -> tuple[float | None, str]:
    """Weighted price of the cheapest HOUR of heating available after the
    measured near term and before the heat is needed (the next goal; the one
    after it when the next is under 1.5 hours away). Future solar is taken
    PESSIMISTICALLY (forecast P10 and high house load), which makes heating
    now look relatively better: the reliable side."""
    deadlines = [goal.deadline for goal in goals]
    if not deadlines or not slots:
        return None, "no_alternative_known"
    horizon = deadlines[0]
    if horizon - now < NEAR_TERM + timedelta(hours=1) and len(deadlines) > 1:
        horizon = deadlines[1]
    candidates = sorted(
        (slot.cost(feed_in, pessimistic=True) / (ELEMENT_KW * slot.hours), slot.hours)
        for slot in slots
        if slot.start >= now + NEAR_TERM and slot.end <= horizon and slot.hours > 0
    )
    total = weighted = 0.0
    for price, hours in candidates:
        take = min(hours, ALTERNATIVE_HOURS - total)
        weighted += price * take
        total += take
        if total >= ALTERNATIVE_HOURS - 1e-9:
            break
    if total < ALTERNATIVE_HOURS - 1e-9:
        return None, "under_one_hour_before_the_heat_is_needed"
    return weighted / total, f"cheapest_hour_before_{horizon.isoformat()}"


class StandbyPermission:
    """Rolling measurements and sustained-condition timers (in memory: after a
    restart the controller re-inspects the heater before it may act)."""

    def __init__(self) -> None:
        self.samples: deque[tuple[datetime, float]] = deque(maxlen=120)
        self.grant_since: datetime | None = None
        self.withdraw_since: datetime | None = None
        self.last: Economics | None = None

    def assess(
        self,
        now: datetime,
        advice,
        settings,
        tariffs,
        decision_at: datetime | None = None,
    ) -> Economics | None:
        """Price the element now. `decision_at` (a peak start about to begin)
        prices the decision at THAT instant's tariff."""
        if advice is None or getattr(advice, "economic_code", None) in GATE_CODES:
            # Outage (no planner, stale or suspect meter): forget the evidence, so recovery needs sustained
            # conditions again before anything is granted or withdrawn.
            self.samples.clear()
            self.grant_since = self.withdraw_since = None
            self.last = None
            return None
        surplus = getattr(advice, "surplus_now_kw", None)
        if surplus is not None:
            self.samples.append((now, float(surplus)))
        while self.samples and now - self.samples[0][0] > ROLLING:
            self.samples.popleft()
        tariff = tariff_at(decision_at or now, tariffs, settings.tariff_clock)
        feed_in = settings.feed_in_rate
        values = sorted(value for _, value in self.samples)
        if values:
            median = values[len(values) // 2]
            current = surplus if surplus is not None else median
            cautious = max(0.0, min(median, current) - HEADROOM_KW)
            share, cost = blended_cost(median, tariff.rate, feed_in)
            _, cautious_cost = blended_cost(cautious, tariff.rate, feed_in)
        else:
            # No meter evidence: no solar credit at all (never assume solar).
            median = cautious = None
            share, cost, cautious_cost = 0.0, tariff.rate, tariff.rate
        alternative, basis = alternative_cost(
            now, getattr(advice, "slots", None) or [], getattr(advice, "goals", None) or [], feed_in
        )
        if alternative is None:
            grant = withdraw = False
        else:
            grant = cautious_cost <= alternative + PERMIT_TOLERANCE and (
                cautious_cost <= alternative - PERMIT_TOLERANCE
                or (median is not None and share >= STRONG_SOLAR_SHARE)
            )
            withdraw = cost > alternative + PARK_MARGIN
        self.grant_since = (self.grant_since or now) if grant else None
        self.withdraw_since = (self.withdraw_since or now) if withdraw else None
        self.last = Economics(
            at=now.isoformat(),
            rate=tariff.rate,
            peak=tariff.kind == "peak",
            feed_in=feed_in,
            surplus_kw=median,
            cautious_surplus_kw=cautious,
            solar_share=share,
            cost_kwh=cost,
            cautious_cost_kwh=cautious_cost,
            alternative_kwh=alternative,
            alternative_basis=basis,
            grant=grant,
            withdraw=withdraw,
        )
        return self.last

    def decide(
        self,
        now: datetime,
        econ: Economics | None,
        permitted: bool,
        peak_soon: bool,
        peak_now: bool = False,
    ) -> tuple[str, str, bool]:
        """(action, reason, urgent). `urgent` lets an economic park during a
        peak bypass the minimum-heating dwell (dwell protects against toggling
        the element; it must not hold peak imports for half an hour).

        Without a usable comparison, permission is never KEPT through a peak
        (about to start or already running): park. Off-peak, hold the current
        state until the comparison is available again."""
        if econ is None or econ.alternative_kwh is None:
            in_peak = peak_now or (econ is not None and econ.peak)
            if permitted and (peak_soon or in_peak):
                reason = "peak_economics_unknown" if in_peak else "peak_starting_economics_unknown"
                return "park", reason, True
            return "hold", "economics_unavailable", False
        if permitted:
            if peak_soon:
                # Decide BEFORE the peak (commands take about a minute): keep
                # permission only when solar already covers the element well
                # enough that peak-rate top-up is cheaper than heating later.
                if econ.grant:
                    return "permit", "solar_justifies_permission_into_peak", False
                return "park", "peak_starting_permission_not_economical", True
            hold = PEAK_HOLD if econ.peak else ECONOMIC_HOLD
            if econ.withdraw and now - self.withdraw_since >= hold:
                reason = "peak_import_not_economical" if econ.peak else "cheaper_heating_later"
                return "park", reason, econ.peak
            return "permit", "economic_permission", False
        if econ.grant and now - self.grant_since >= ECONOMIC_HOLD:
            strong = (econ.solar_share or 0) >= STRONG_SOLAR_SHARE
            return "permit", "solar_permission" if strong else "economic_permission", False
        return "park", "permission_not_economical", False
