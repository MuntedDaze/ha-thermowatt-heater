"""Full-power counterfactual costs; no physical state or execution assumptions."""

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta

from .model import ELEMENT_KW, Forecast, Settings, Tariff, tariff_at


@dataclass(frozen=True)
class Quote:
    start: datetime
    end: datetime
    cost: float
    solar_kwh: float
    import_kwh: float


def unit_cost(export_kw: float, rate: float, feed_in: float) -> tuple[float, float]:
    """Solar has an opportunity cost. The element always draws the full 3 kW."""
    fraction = min(1.0, max(0.0, export_kw) / ELEMENT_KW)
    return rate * (1 - fraction) + feed_in * fraction, fraction


def compare(
    now: datetime,
    deadline: datetime,
    energy: float,
    export_kw: float,
    settings: Settings,
    tariffs: tuple[Tariff, ...],
    forecast: tuple[Forecast, ...] = (),
    latest_optional_start: datetime | None = None,
) -> tuple[Quote | None, Quote | None]:
    """Compare a continuous cycle now with feasible later continuous cycles.

    Minute-resolution tariffs; forecast boundaries are exact. Gaps mean zero
    solar. Recent measured export takes priority for a bounded near-term window.
    Future candidates are five minutes apart plus every tariff/forecast boundary.
    A conservative fallback reservation bounds how long an optional start waits.
    """
    if energy <= 1e-8 or deadline <= now:
        return None, None
    duration = energy / ELEMENT_KW * 3600
    if duration > (deadline - now).total_seconds() + 1e-6:
        return None, None
    times, costs, solar = [0.0], [0.0], [0.0]
    candidates = {0.0}
    cursor = now
    previous_rate = None
    recent_end = now + timedelta(minutes=settings.solar_window_minutes)
    while cursor < deadline:
        end = min(cursor.replace(second=0, microsecond=0) + timedelta(minutes=1), deadline)
        surplus = 0.0
        for item in forecast:
            if cursor < item.start < end:
                end = item.start
            if cursor < item.end < end:
                end = item.end
            if item.start <= cursor < item.end:
                surplus = max(0.0, item.export_kw - settings.export_headroom_kw)
        if cursor < recent_end:
            end = min(end, recent_end)
            surplus = max(0, export_kw - settings.export_headroom_kw)
        tariff = tariff_at(cursor, tariffs, settings.tariff_clock)
        second = (cursor - now).total_seconds()
        if (
            tariff.rate != previous_rate
            or second % 300 == 0
            or any(cursor in (item.start, item.end) for item in forecast)
        ):
            candidates.add(second)
        previous_rate = tariff.rate
        cost, fraction = unit_cost(surplus, tariff.rate, settings.feed_in_rate)
        amount = ELEMENT_KW * (end - cursor).total_seconds() / 3600
        times.append((end - now).total_seconds())
        costs.append(costs[-1] + amount * cost)
        solar.append(solar[-1] + amount * fraction)
        cursor = end

    def cumulative(values: list[float], second: float) -> float:
        index = min(bisect_right(times, second) - 1, len(times) - 2)
        part = (second - times[index]) / (times[index + 1] - times[index])
        return values[index] + part * (values[index + 1] - values[index])

    def quote(second: float) -> Quote:
        solar_energy = cumulative(solar, second + duration) - cumulative(solar, second)
        return Quote(
            now + timedelta(seconds=second),
            now + timedelta(seconds=second + duration),
            cumulative(costs, second + duration) - cumulative(costs, second),
            solar_energy,
            energy - solar_energy,
        )

    latest = min(deadline - timedelta(seconds=duration), latest_optional_start or deadline)
    candidates.add(max(0.0, (latest - now).total_seconds()))
    later = [
        quote(second)
        for second in candidates
        if second >= 300
        and now + timedelta(seconds=second) <= latest
        and second + duration <= times[-1] + 1e-6
    ]
    return quote(0), min(later, key=lambda q: (q.cost, -q.start.timestamp()), default=None)
