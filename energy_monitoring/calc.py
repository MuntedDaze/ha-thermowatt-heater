"""Reference calculations, in plain Python.

The Home Assistant templates in the generated package implement the same
arithmetic; the offline tests render those templates and compare them with
these functions. The reporting tool and any later learning module can import
this file directly: it has no Home Assistant dependency.

Units: power in W, energy in kWh, money in the map's currency.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

MAX_STEP_KWH = 20.0


def split_grid(power: float, export_positive: bool = True) -> tuple[float, float]:
    """Signed meter power as (import, export), both non-negative."""
    exporting = power if export_positive else -power
    return max(0.0, -exporting), max(0.0, exporting)


def self_consumed(solar: float, export: float) -> float:
    """Solar used on site: generation that was not exported."""
    return max(0.0, solar - export)


def attribute_load(load: float, grid_import: float) -> tuple[float, float]:
    """Split a deferrable load into (from grid, from solar).

    Marginal attribution: switching the load off would first remove the grid
    import and only then raise export, so the load is charged with
    ``min(load, import)`` and the remainder is solar.
    """
    load = abs(load)
    from_grid = min(load, max(0.0, grid_import))
    return from_grid, load - from_grid


def untracked(house: float, tracked: list[float]) -> tuple[float, float]:
    """(untracked power, raw residual). ``tracked`` must be non-overlapping.

    A persistently negative residual means a load is counted twice, or the
    house and appliance readings are badly misaligned in time.
    """
    residual = max(0.0, house) - sum(tracked)
    return max(0.0, residual), residual


def tariff_period(moment: datetime, tariff: dict) -> str:
    """``peak`` or ``off_peak`` for an aware datetime.

    ``clock: standard`` uses a fixed UTC offset (Aurora Tariff 93 stays on AEST
    through daylight saving); ``clock: local`` uses the datetime's own zone.
    Windows hold ``start``/``end`` as minutes after midnight (see mapping.py).
    """
    if moment.tzinfo is None:
        raise ValueError("an aware datetime is required")
    if tariff["clock"] == "standard":
        moment = moment.astimezone(timezone(timedelta(hours=tariff["utc_offset_hours"])))
    minute = moment.hour * 60 + moment.minute
    for window in tariff["peak_windows"]:
        if moment.weekday() in window["days"] and window["start"] <= minute < window["end"]:
            return "peak"
    return "off_peak"


def _number(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


@dataclass
class Accumulator:
    """Cumulative total of ``meter step x factor`` (factor = price, or 1).

    Keeps the last numeric reading, so an unavailable gap loses nothing. A
    negative step (meter reset or replaced) or one above ``MAX_STEP_KWH`` only
    moves the baseline. Steps that arrive with no price are counted in
    ``unpriced`` so the gap is visible rather than silently costed at zero.
    """

    total: float = 0.0
    last_reading: float | None = None
    unpriced: float = 0.0

    def update(self, reading, factor: float = 1.0) -> float:
        new = _number(reading)
        if new is None:
            return self.total
        step = new - self.last_reading if self.last_reading is not None else 0.0
        if not 0 < step <= MAX_STEP_KWH:
            step = 0.0
        self.total += step * factor
        if factor <= 0:
            self.unpriced += step
        self.last_reading = new
        return self.total


def self_consumption_percent(solar_kwh: float, export_kwh: float) -> float | None:
    """Share of generation used on site; ``None`` before any generation."""
    if solar_kwh <= 0.05:
        return None
    return max(0.0, min(100.0, 100 * (solar_kwh - export_kwh) / solar_kwh))


def house_energy(import_kwh: float, solar_kwh: float, export_kwh: float) -> float:
    """Energy balance of three cumulative meters over the same period."""
    return max(0.0, import_kwh + solar_kwh - export_kwh)


def self_sufficiency_percent(import_kwh: float, solar_kwh: float, export_kwh: float):
    """Share of consumption not imported; ``None`` before any consumption."""
    used = import_kwh + solar_kwh - export_kwh
    if used <= 0.05:
        return None
    return max(0.0, min(100.0, 100 * (1 - import_kwh / used)))


def net_cost(import_cost: float, export_earnings: float, supply_per_day: float, days: int = 1):
    """What the period costs: imports, less feed-in, plus the supply charge."""
    return import_cost - export_earnings + supply_per_day * days


def cycle_summary(start: dict, end: dict) -> dict:
    """One heating cycle from two snapshots.

    Each snapshot: ``time`` (aware datetime), ``energy_kwh``, ``grid_kwh``,
    ``solar_kwh`` (cumulative meters) and optionally ``temperature_c``.
    Missing readings give ``None`` for the affected figure, never a guess.
    """

    def delta(key, digits=3):
        first, last = _number(start.get(key)), _number(end.get(key))
        return None if first is None or last is None else round(last - first, digits)

    minutes = round((end["time"] - start["time"]).total_seconds() / 60, 1)
    energy, solar = delta("energy_kwh"), delta("solar_kwh")
    return {
        "started": start["time"],
        "ended": end["time"],
        "duration_minutes": minutes,
        "energy_kwh": energy,
        "grid_kwh": delta("grid_kwh"),
        "solar_kwh": solar,
        "solar_fraction": round(solar / energy, 3) if energy and solar is not None else None,
        "average_power_w": round(energy * 60000 / minutes) if energy and minutes > 0 else None,
        "temperature_rise_c": delta("temperature_c", 1),
    }


def period_key(day: date, period: str) -> str:
    """Label of the calendar period a local date falls in (ISO weeks)."""
    if period == "day":
        return day.isoformat()
    if period == "week":
        year, week, _ = day.isocalendar()
        return f"{year}-W{week:02d}"
    if period == "month":
        return f"{day.year}-{day.month:02d}"
    if period == "year":
        return str(day.year)
    raise ValueError(f"unknown period {period!r}")


def rollup(daily: dict[date, float], period: str) -> dict[str, float]:
    """Sum daily totals by local calendar period.

    Working from local dates makes daylight saving a non-issue: a 23- or
    25-hour day is still exactly one day.
    """
    totals: dict[str, float] = {}
    for day in sorted(daily):
        key = period_key(day, period)
        totals[key] = totals.get(key, 0.0) + daily[day]
    return totals


@dataclass
class DayCost:
    """Cost of one day's metered energy at the given rates."""

    peak_kwh: float = 0.0
    off_peak_kwh: float = 0.0
    export_kwh: float = 0.0
    rates: dict = field(default_factory=dict)

    @property
    def import_cost(self) -> float:
        return self.peak_kwh * self.rates["peak"] + self.off_peak_kwh * self.rates["off_peak"]

    @property
    def export_earnings(self) -> float:
        return self.export_kwh * self.rates["feed_in"]

    @property
    def net(self) -> float:
        return net_cost(self.import_cost, self.export_earnings, self.rates.get("supply", 0.0))
