"""Dynamic comfort deadlines and tariff boundaries. Pure functions, no I/O.

Aurora Tariff 93 times are Australian Eastern Standard Time (fixed UTC+10), so
in Hobart daylight time every boundary appears one hour later. Comfort deadlines
default to the START of the applicable peak period (morning and evening), found
by scanning the configured tariff table itself, so no 07:00/08:00/16:00/17:00
clock time is hardcoded. Weekends (no peak) use separately configured household
times. An optional weekday shower-ready time can make the morning deadline
EARLIER, never later.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .model import HOBART, UTC, Settings, Tariff, tariff_at


@dataclass(frozen=True)
class Goal:
    kind: str  # "morning" | "afternoon"
    deadline: datetime  # UTC
    target_c: float
    basis: str  # "tariff_peak_start" | "shower_time" | "household_time"
    peak_start: datetime | None  # the related peak start, if any (UTC)


def peak_start(
    day: date,
    tariffs: tuple[Tariff, ...],
    clock: str,
    first_hour: int,
    last_hour: int,
) -> datetime | None:
    """First instant in [first_hour, last_hour) Hobart local on `day` that is peak.

    Scans real instants minute by minute in UTC, so DST start/end days (23 h and
    25 h) are handled by the zone rules rather than by arithmetic on clock times.
    """
    start = datetime.combine(day, time(first_hour), HOBART).astimezone(UTC)
    end = (
        datetime.combine(day, time(last_hour), HOBART)
        if last_hour < 24
        else datetime.combine(day + timedelta(days=1), time(0), HOBART)
    ).astimezone(UTC)
    instant = start
    previous = tariff_at(instant - timedelta(minutes=1), tariffs, clock).kind
    while instant < end:
        kind = tariff_at(instant, tariffs, clock).kind
        if kind == "peak" and (previous != "peak" or instant == start):
            return instant
        previous = kind
        instant += timedelta(minutes=1)
    return None


def goals_for_day(day: date, settings: Settings, tariffs: tuple[Tariff, ...]) -> list[Goal]:
    verified = settings.tariff_verified
    morning_peak = peak_start(day, tariffs, settings.tariff_clock, 0, 12) if verified else None
    evening_peak = peak_start(day, tariffs, settings.tariff_clock, 12, 24) if verified else None
    if morning_peak is not None:
        deadline, basis = morning_peak, "tariff_peak_start"
    else:
        deadline = datetime.combine(day, settings.morning, HOBART).astimezone(UTC)
        basis = "household_time"
    if settings.shower_time_enabled and morning_peak is not None:
        shower = datetime.combine(day, settings.shower_time, HOBART).astimezone(UTC)
        if shower < deadline:
            deadline, basis = shower, "shower_time"
    morning = Goal("morning", deadline, settings.morning_threshold_c, basis, morning_peak)
    if evening_peak is not None:
        afternoon = Goal(
            "afternoon", evening_peak, settings.target_c, "tariff_peak_start", evening_peak
        )
    else:
        afternoon = Goal(
            "afternoon",
            datetime.combine(day, settings.evening, HOBART).astimezone(UTC),
            settings.target_c,
            "household_time",
            None,
        )
    return [morning, afternoon]


def upcoming_goals(
    now: datetime, settings: Settings, tariffs: tuple[Tariff, ...], days: int = 2
) -> list[Goal]:
    """Goals with deadlines after `now`, earliest first (today and tomorrow)."""
    today = now.astimezone(HOBART).date()
    goals = []
    for offset in range(days):
        goals.extend(goals_for_day(today + timedelta(days=offset), settings, tariffs))
    return sorted((goal for goal in goals if goal.deadline > now), key=lambda g: g.deadline)


def next_tariff_change(
    now: datetime,
    tariffs: tuple[Tariff, ...],
    clock: str,
    horizon: timedelta = timedelta(hours=80),
) -> tuple[datetime, Tariff] | None:
    """Next instant at which the tariff period (kind or rate) changes, and the new period."""
    current = tariff_at(now, tariffs, clock)
    instant = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = now + horizon
    while instant <= end:
        item = tariff_at(instant, tariffs, clock)
        if item.kind != current.kind or item.rate != current.rate:
            return instant, item
        instant += timedelta(minutes=1)
    return None
