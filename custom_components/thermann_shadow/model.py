"""Deterministic shadow scenarios. No I/O, actuation, quota resets or HA dependency.

The uniform-tank model is NOT a usable-water reserve or hygiene measurement.
Plans are advisory counterfactuals while native Schedule retains all ownership.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import math
from zoneinfo import ZoneInfo

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


@dataclass(frozen=True)
class Forecast:
    start: datetime
    end: datetime
    export_kw: float  # forecast NET export, after household load; never PV alone


@dataclass(frozen=True)
class Settings:
    meter_verified: bool = False
    tariff_verified: bool = False
    paused: bool = False
    import_positive: bool = True
    tariff_clock: str = "local"
    target_c: float = 70.0  # model target only; never a heater setpoint
    morning_threshold_c: float = 42.0  # HARD morning minimum; NEVER a storage setpoint
    morning_preferred_c: float = 45.0  # preferred morning reserve (soft); NEVER a setpoint
    expected_native_target_c: float = 70.0
    margin_minutes: float = 30.0
    feed_in_rate: float = 0.08
    export_headroom_kw: float = 0.3
    status_max_age_minutes: float = 45.0
    grid_max_age_seconds: float = 120.0
    solar_hold_minutes: float = 10.0
    solar_window_minutes: float = 15.0
    min_solar_kw: float = 0.1
    switching_benefit_aud: float = 0.10
    solar_loss_minutes: float = 20.0
    minimum_cycle_minutes: float = 30.0
    minimum_gap_minutes: float = 30.0
    forecast_enabled: bool = False
    forecast_uncertainty: float = 0.25
    forecast_max_age_minutes: float = 120.0
    forecast_house_margin_kw: float = 0.3
    expected_morning_draw_c: float = 10.0  # owner assumption, not a measurement
    standing_loss_c_per_hour: float = 0.2  # owner assumption, not a measurement
    wait_benefit_aud_per_kwh: float = 0.05
    pv_ac_limit_kw: float = 5.0  # one GoodWe GW5000 inverter, shared by both arrays
    base_load_source: str = "measured_only"
    shower_time_enabled: bool = False
    # Household times used when a day has no peak (weekends); the weekday
    # deadlines follow the tariff's actual peak starts (fixed AEST).
    morning: time = time(8)
    evening: time = time(16)
    shower_time: time = time(7)
    # 0.7.0 morning comfort, EVERY day (Hobart local): at least the morning
    # threshold by the preferred time; the hard deadline is never abandoned
    # when the preferred time is missed.
    morning_preferred: time = time(6)
    morning_hard: time = time(7)


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


_TARIFF_CACHE: dict[tuple[float, int, str], tuple[tuple[Tariff, ...], Tariff]] = {}


def tariff_at(at: datetime, tariffs: tuple[Tariff, ...], clock: str) -> Tariff:
    # Tariffs change on wall-minute boundaries only: memoise per UTC minute and
    # tariff-table identity (the cached entry holds the table, so ids stay valid).
    key = (at.timestamp() // 60, id(tariffs), clock)
    hit = _TARIFF_CACHE.get(key)
    if hit is not None and hit[0] is tariffs:
        return hit[1]
    result = _tariff_at_minute(at, tariffs, clock)
    if len(_TARIFF_CACHE) >= 50000:
        _TARIFF_CACHE.clear()
    _TARIFF_CACHE[key] = (tariffs, result)
    return result


def _tariff_at_minute(at: datetime, tariffs: tuple[Tariff, ...], clock: str) -> Tariff:
    local = at.astimezone(HOBART if clock == "local" else STANDARD)
    minute = local.hour * 60 + local.minute
    matches = []
    for item in tariffs:
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


def validate_tariffs(tariffs: tuple[Tariff, ...], clock: str) -> None:
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
        ):
            raise ValueError("tariff_invalid")
    # A whole local week, outside DST, proves minute coverage including overnight
    # weekday/weekend boundaries. Runtime UTC iteration also covers both DST folds.
    start = datetime(2026, 6, 1, tzinfo=HOBART if clock == "local" else STANDARD)
    for minute in range(7 * 1440):
        tariff_at(start + timedelta(minutes=minute), tariffs, clock)


def _fresh(reading: Reading, now: datetime, boot: datetime, seconds: float) -> None:
    if (
        reading.restored
        or not aware(reading.observed_at)
        or reading.observed_at < boot
        or not 0 <= (now - reading.observed_at).total_seconds() <= seconds
    ):
        raise ValueError("input_stale_or_restored")


def _present(reading: Reading) -> None:
    if reading.restored or not aware(reading.observed_at):
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
            for key in (
                "paused",
                "meter_verified",
                "tariff_verified",
                "import_positive",
                "forecast_enabled",
                "shower_time_enabled",
            )
        )
        or settings.tariff_clock not in {"local", "standard"}
        or settings.base_load_source not in {"measured_only", "measured_then_published"}
        or not 0 <= settings.expected_morning_draw_c <= 40
        or not 0 <= settings.standing_loss_c_per_hour <= 2
        or not 0 <= settings.wait_benefit_aud_per_kwh <= 0.5
        or not 1 <= settings.pv_ac_limit_kw <= 30
        or not isinstance(settings.shower_time, time)
        or settings.shower_time.tzinfo is not None
        or not time(0) <= settings.shower_time <= time(11, 59)
        or not 65 <= settings.target_c <= 70
        or not 30 <= settings.morning_threshold_c <= 60
        or not settings.morning_threshold_c <= settings.morning_preferred_c <= 60
        or not 20 <= settings.expected_native_target_c <= 75
        or not 0 <= settings.margin_minutes <= 120
        or not 35 <= settings.status_max_age_minutes <= 90
        or not 30 <= settings.grid_max_age_seconds <= 300
        or not 0 <= settings.export_headroom_kw <= 3
        or not 0 <= settings.feed_in_rate <= 2
        or not 5 <= settings.solar_hold_minutes <= 30
        or not 5 <= settings.solar_window_minutes <= 30
        or not 0 <= settings.min_solar_kw <= 3
        or not 0 <= settings.switching_benefit_aud <= 5
        or not 0 <= settings.solar_loss_minutes <= 120
        or not 0 <= settings.minimum_cycle_minutes <= 180
        or not 0 <= settings.minimum_gap_minutes <= 180
        or not 0 <= settings.forecast_uncertainty <= 0.9
        or not 35 <= settings.forecast_max_age_minutes <= 360
        or not 0 <= settings.forecast_house_margin_kw <= 5
        or not isinstance(settings.morning, time)
        or settings.morning.tzinfo is not None
        or not isinstance(settings.evening, time)
        or settings.evening.tzinfo is not None
        or not time(0) <= settings.morning <= time(11, 59)
        or any(
            not isinstance(value, time) or value.tzinfo is not None
            for value in (settings.morning_preferred, settings.morning_hard)
        )
        or not time(0) <= settings.morning_preferred <= settings.morning_hard <= time(11, 59)
        or not time(12) <= settings.evening <= time(23, 59)
    ):
        raise ValueError("settings_invalid")
