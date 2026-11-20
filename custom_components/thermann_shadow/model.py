"""Shared value types, parsed settings and the tariff calendar.

No I/O, actuation, quota resets or Home Assistant dependency.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

HOBART = ZoneInfo("Australia/Hobart")
STANDARD = timezone(timedelta(hours=10))
UTC = timezone.utc
TANK_KWH_PER_C = 315 * 4.186 / 3600
ELEMENT_KW = 3.0


@dataclass(frozen=True)
class Reading:
    value: object
    observed_at: datetime
    unit: str | None = None
    restored: bool = False


@dataclass(frozen=True)
class Tariff:
    days: tuple[int, ...]
    start: int  # wall minutes, inclusive; overnight periods belong to start day
    end: int  # exclusive; equal start/end means 24 hours
    rate: float  # AUD/kWh; no vendor tariff is assumed
    kind: str
    months: tuple[int, ...] = tuple(range(1, 13))


@dataclass(frozen=True)
class Forecast:
    start: datetime
    end: datetime
    export_kw: float  # forecast NET export, after household load; never PV alone


@dataclass(frozen=True)
class Settings:
    """Parsed household settings that the active code reads (0.18.0)."""

    meter_verified: bool = False
    tariff_verified: bool = False
    import_positive: bool = True
    tariff_clock: str = "local"
    time_zone: str = "Australia/Hobart"  # legacy fallback; fresh entries use HA's zone
    feed_in_rate: float = 0.08
    status_max_age_minutes: float = 45.0
    grid_max_age_seconds: float = 120.0
    forecast_enabled: bool = False
    forecast_uncertainty: float = 0.25
    forecast_max_age_minutes: float = 120.0
    forecast_house_margin_kw: float = 0.3
    pv_ac_limit_kw: float = 5.0  # one GoodWe GW5000 inverter, shared by both arrays
    tank_litres: float = 315.0
    element_kw: float = 3.0


def number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, float, int)):
        raise ValueError("number_invalid")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("number_invalid")
    return result


def aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp_invalid")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not aware(result):
        raise ValueError("timestamp_invalid")
    return result.astimezone(UTC)


_TARIFF_CACHE: dict[tuple[float, int, str, str], tuple[tuple[Tariff, ...], Tariff]] = {}


def tariff_zone(at: datetime, clock: str, zone: str = "Australia/Hobart") -> tzinfo:
    try:
        local = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ValueError("time_zone_invalid") from None
    if clock == "local":
        return local
    # Separate fixed standard clock, including half-hour offsets. It does not
    # acquire the site's current daylight-saving offset.
    sample = at.astimezone(local)
    return timezone((sample.utcoffset() or timedelta()) - (sample.dst() or timedelta()))


def tariff_at(
    at: datetime, tariffs: tuple[Tariff, ...], clock: str, zone: str = "Australia/Hobart"
) -> Tariff:
    # Tariffs change on wall-minute boundaries only: memoise per UTC minute and
    # tariff-table identity (the cached entry holds the table, so ids stay valid).
    key = (at.timestamp() // 60, id(tariffs), clock, zone)
    hit = _TARIFF_CACHE.get(key)
    if hit is not None and hit[0] is tariffs:
        return hit[1]
    result = _tariff_at_minute(at, tariffs, clock, zone)
    if len(_TARIFF_CACHE) >= 50000:
        _TARIFF_CACHE.clear()
    _TARIFF_CACHE[key] = (tariffs, result)
    return result


def _tariff_at_minute(
    at: datetime, tariffs: tuple[Tariff, ...], clock: str, zone: str = "Australia/Hobart"
) -> Tariff:
    local = at.astimezone(tariff_zone(at, clock, zone))
    minute = local.hour * 60 + local.minute
    matches = []
    for item in tariffs:
        if local.month not in item.months:
            continue
        today = local.weekday() in item.days
        previous = (local.weekday() - 1) % 7 in item.days
        if (
            (item.start < item.end and today and item.start <= minute < item.end)
            or (
                item.start > item.end
                and ((today and minute >= item.start) or (previous and minute < item.end))
            )
            or (item.start == item.end and today)
        ):
            matches.append(item)
    if len(matches) != 1:
        raise ValueError("tariff_gap_or_overlap")
    return matches[0]


def validate_tariffs(
    tariffs: tuple[Tariff, ...], clock: str, zone: str = "Australia/Hobart"
) -> None:
    if clock not in {"local", "standard"} or not 1 <= len(tariffs) <= 32:
        raise ValueError("tariff_invalid")
    for item in tariffs:
        if (
            not item.days
            or any(type(day) is not int or not 0 <= day <= 6 for day in item.days)
            or len(set(item.days)) != len(item.days)
            or not 0 <= item.start < 1440
            or not 0 <= item.end < 1440
            or not math.isfinite(item.rate)
            or not -5 <= item.rate <= 10
            or item.kind not in {"off_peak", "shoulder", "peak"}
            or not item.months
            or any(type(month) is not int or not 1 <= month <= 12 for month in item.months)
            or len(set(item.months)) != len(item.months)
        ):
            raise ValueError("tariff_invalid")
    tariff_zone(datetime(2026, 1, 1, tzinfo=UTC), clock, zone)
    # Sweep boundaries for every month and weekday, including overnight tails.
    # Month selection follows the current tariff-clock date at midnight.
    for month in range(1, 13):
        edges: list[list[tuple[int, int]]] = [[(0, 0), (1440, 0)] for _ in range(7)]
        for item in tariffs:
            if month not in item.months:
                continue
            for day in item.days:
                if item.start == item.end:
                    edges[day] += [(0, 1), (1440, -1)]
                elif item.start < item.end:
                    edges[day] += [(item.start, 1), (item.end, -1)]
                else:
                    edges[day] += [(item.start, 1), (1440, -1)]
                    edges[(day + 1) % 7] += [(0, 1), (item.end, -1)]
        for day_edges in edges:
            level, previous = 0, 0
            for boundary, delta in sorted(day_edges):
                if boundary > previous and level != 1:
                    raise ValueError("tariff_gap_or_overlap")
                level += delta
                previous = boundary


def _fresh(reading: Reading, now: datetime, boot: datetime, seconds: float) -> None:
    if (
        reading.restored
        or not aware(reading.observed_at)
        or reading.observed_at < boot
        or not 0 <= (now - reading.observed_at).total_seconds() <= seconds
    ):
        raise ValueError("input_stale_or_restored")


def _power(reading: Reading) -> float:
    if reading.unit not in {"W", "kW"}:
        raise ValueError("grid_power_unit_invalid")
    result = number(reading.value) / (1000 if reading.unit == "W" else 1)
    if abs(result) > 30:
        raise ValueError("grid_power_out_of_range")
    return result


def validate_settings(settings: Settings) -> None:
    if (
        any(
            type(getattr(settings, key)) is not bool
            for key in ("meter_verified", "tariff_verified", "import_positive", "forecast_enabled")
        )
        or settings.tariff_clock not in {"local", "standard"}
        or not 1 <= settings.pv_ac_limit_kw <= 30
        or not 50 <= settings.tank_litres <= 500
        or not 2 <= settings.element_kw <= 3.6
        or not 35 <= settings.status_max_age_minutes <= 90
        or not 30 <= settings.grid_max_age_seconds <= 300
        or not 0 <= settings.feed_in_rate <= 2
        or not 0 <= settings.forecast_uncertainty <= 0.9
        or not 35 <= settings.forecast_max_age_minutes <= 360
        or not 0 <= settings.forecast_house_margin_kw <= 5
    ):
        raise ValueError("settings_invalid")
