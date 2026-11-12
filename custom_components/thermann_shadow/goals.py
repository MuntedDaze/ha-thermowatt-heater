"""Dynamic comfort deadlines and tariff boundaries. Pure functions, no I/O.

Aurora Tariff 93 times are Australian Eastern Standard Time (fixed UTC+10), so
in Hobart daylight time every boundary appears one hour later. The AFTERNOON
deadline is the START of the evening peak, found by scanning the configured
tariff table itself (no 16:00/17:00 clock time is hardcoded); weekends (no
peak) use the configured household evening time.

The MORNING goal (0.7.0) is a household comfort time, every day, Hobart local:
the threshold should be reached by the preferred time (06:00 by default), and
the hard deadline (07:00, showers) is never abandoned: once the preferred time
passes unmet, the same goal moves to the hard deadline.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

from .model import HOBART, UTC, Settings, Tariff, tariff_at


@dataclass(frozen=True)
class Goal:
    kind: str  # "morning" | "afternoon"
    deadline: datetime  # UTC
    target_c: float
    basis: str  # "tariff_peak_start" | "household_time" | morning: see goals_for_day
    peak_start: datetime | None  # the related peak start, if any (UTC)
    hard_deadline: datetime | None = None  # morning only: never abandoned (UTC)


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
    preferred = datetime.combine(day, settings.morning_preferred, HOBART).astimezone(UTC)
    hard = datetime.combine(day, settings.morning_hard, HOBART).astimezone(UTC)
    morning = Goal(
        "morning",
        preferred,
        settings.morning_threshold_c,
        "preferred_morning_time",
        morning_peak,
        hard,
    )
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
    """Goals with deadlines after `now`, earliest first (today and tomorrow).

    A morning goal whose preferred time has passed is NOT dropped: until its
    hard deadline it stays, with the hard deadline as its deadline."""
    today = now.astimezone(HOBART).date()
    goals = []
    for offset in range(days):
        for goal in goals_for_day(today + timedelta(days=offset), settings, tariffs):
            if goal.hard_deadline is not None and goal.deadline <= now < goal.hard_deadline:
                goal = replace(goal, deadline=goal.hard_deadline, basis="hard_morning_deadline")
            goals.append(goal)
    return sorted((goal for goal in goals if goal.deadline > now), key=lambda g: g.deadline)


HOLIDAY_PREPARATION = timedelta(hours=24)


def holiday_goals(
    goals: list[Goal],
    window: tuple[datetime, datetime] | None,
    settings: Settings,
    now: datetime | None = None,
) -> list[Goal]:
    """Holiday (0.7.0): no comfort goal while away. ONE goal at the return
    time (full storage target) appears only in the last 24 hours (about the
    forecast horizon), so the planner picks the cheapest feasible heating just
    before the owner is back instead of heating days early and losing it.
    Goals after the return are unchanged."""
    if window is None:
        return goals
    start, back = window
    kept = [goal for goal in goals if not start <= goal.deadline < back]
    if now is None or now >= back - HOLIDAY_PREPARATION:
        kept.append(Goal("return", back, settings.target_c, "holiday_return", None))
    return sorted(kept, key=lambda goal: goal.deadline)


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
