"""Optional EMHASS forecast adapter: read-only HA attributes, never HTTP.

Forecasts are an optimisation input only (docs/OPERATING_POLICY.md §1.11). They
may choose WHEN required 62 °C heating starts and refine the economics of a
solar boost, but they never authorise a boost (only fresh measured export can
qualify surplus) and their loss never stops required heating: weekday and
weekend deadlines and the tariff rules continue unchanged.

0.18.1: only the EMHASS published ``forecasts`` series is accepted for PV and
household load. The alternative Forecast.Solar ``watts`` shape and the flat
Statistics-helper household baseline are retired; an unusable household load
uses the single conservative floor below, never a second load model.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .model import Forecast, Settings, number, timestamp

# A measured-vs-forecast PV error says most about the next hour or two. Its
# down-correction fades linearly to no correction over this horizon, so one
# cloudy morning reading cannot erase a sunny afternoon forecast.
CORRECTION_HOURS = 3.0
# Points further apart than this are a GAP (e.g. Forecast.Solar overnight), not
# a held prediction. A gap produces no forecast interval, i.e. zero solar.
MAX_POINT_GAP_SECONDS = 7200
# Two-way bound on the measured-vs-forecast PV factor. Downward is unbounded
# (heavy cloud is real); upward is capped so one bright reading cannot inflate
# the afternoon. While the inverter clips, measured AC is only a LOWER bound.
MAX_UPWARD_CORRECTION = 1.3
CLIPPING_MARGIN_KW = 0.15
# Explicit conservative assumption when published demand is unusable. This is
# not a learned daily average, and cannot authorise an optional solar start.
FALLBACK_LOAD_KW = 1.0
MIN_LOAD_KW = 0.1


@dataclass
class ForecastResult:
    slots: tuple[Forecast, ...] = ()
    source: str = "disabled"
    age_minutes: float | None = None
    pv_error_kw: float | None = None
    correction: float = 1.0
    correction_hours: float = CORRECTION_HOURS
    measured_pv_average_kw: float | None = None
    load_basis: str | None = None
    load_quality: str = "unknown"
    load_floor_kw: float | None = None
    pv_series: tuple = ()  # ((start, end, AC kW corrected and clipped), ...)
    load_series: tuple = ()  # ((start, end, published household kW), ...)
    clipped_now: bool = False
    warnings: list[str] = field(default_factory=list)


def _generated(state, now: datetime, boot: datetime, settings: Settings) -> float:
    # last_reported alone is NOT forecast generation time: EMHASS may republish
    # an old plan. Require explicit provenance on a small owner template sensor.
    generated = timestamp(state.attributes.get("forecast_generated_at"))
    age = (now - generated).total_seconds() / 60
    if generated < boot or not 0 <= age <= settings.forecast_max_age_minutes:
        raise ValueError("forecast_stale_or_pre_restart")
    return age


def _available(state) -> None:
    if (
        state is None
        or state.attributes.get("restored")
        or state.state in {"unavailable", "unknown"}
    ):
        raise ValueError("forecast_missing")


def _series(state, kind: str, now: datetime, boot: datetime, settings: Settings):
    _available(state)
    age = _generated(state, now, boot, settings)
    unit = state.attributes.get("unit_of_measurement")
    if unit not in {"W", "kW"}:
        raise ValueError("forecast_unit_invalid")
    raw = state.attributes.get("forecasts")
    key = "p_pv_forecast" if kind == "pv" else "p_load_forecast"
    if not isinstance(raw, (list, tuple)) or not 2 <= len(raw) <= 577:
        raise ValueError("forecast_series_invalid")
    points = []
    for row in raw:
        if not isinstance(row, Mapping):
            raise ValueError("forecast_series_invalid")
        name = key
        if key not in row:
            # EMHASS names the value after its published entity, so a custom
            # entity ID (e.g. sensor.mpc_pv_forecast) has exactly one other key.
            others = [item for item in row if item != "date"]
            if len(others) != 1:
                raise ValueError("forecast_series_invalid")
            name = others[0]
        at, value = timestamp(row.get("date")), number(row.get(name))
        value /= 1000 if unit == "W" else 1
        if not 0 <= value <= 30 or (points and at <= points[-1][0]):
            raise ValueError("forecast_series_invalid")
        points.append((at, value))
    # The last timestamp is an end boundary, not an indefinitely held prediction.
    if points[-1][0] > now + timedelta(hours=48):
        raise ValueError("forecast_series_invalid")
    return points, age


def _value_at(points, at):
    """Step-held value over [a, b); None in a gap or outside the series."""
    for a, b in zip(points, points[1:], strict=False):
        if a[0] <= at < b[0]:
            return a[1] if (b[0] - a[0]).total_seconds() <= MAX_POINT_GAP_SECONDS else None
    return None


def build_forecast(
    now, boot, settings, pv_state, load_state, measured_pv=None, measured_house=None
):
    result = ForecastResult()
    if not settings.forecast_enabled:
        return result
    try:
        pv, pv_age = _series(pv_state, "pv", now, boot, settings)
        try:
            load, load_age = _series(load_state, "load", now, boot, settings)
            result.load_basis = "published_household_load_forecast"
            result.load_quality = "published_uncertain"
            if any(value < MIN_LOAD_KW for _, value in load):
                raise ValueError("household_forecast_zero_or_insufficient")
        except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
            # Keep independently valid PV provenance. Missing demand never
            # becomes zero. The current household value can only raise this
            # assumed flat floor; do not invent a daily appliance schedule.
            floor = FALLBACK_LOAD_KW
            if measured_house is not None:
                try:
                    current = number(measured_house)
                    if 0 < current <= 30:
                        floor = max(floor, current)
                except (ValueError, TypeError, OverflowError):
                    pass
            load = [(now + timedelta(hours=hour), floor) for hour in range(49)]
            load_age = 0
            result.load_basis = "conservative_assumed_household_floor"
            result.load_quality = "provisional_not_daily_history"
            result.load_floor_kw = floor
            result.warnings.append("household_history_insufficient_using_assumed_load_floor")
        result.age_minutes = round(max(pv_age, load_age), 1)
        result.source = "published_pv_and_house_load"
        limit = settings.pv_ac_limit_kw
        expected = _value_at(pv, now)
        if expected is not None and measured_pv is not None and expected > 0.1:
            achievable = min(expected, limit)
            result.pv_error_kw = round(measured_pv - achievable, 3)
            ratio = measured_pv / achievable
            result.clipped_now = measured_pv >= limit - CLIPPING_MARGIN_KW
            if result.clipped_now:
                # Clipped output hides the true potential: never correct downward.
                ratio = max(1.0, ratio)
            result.correction = round(min(MAX_UPWARD_CORRECTION, max(0.0, ratio)), 4)
        boundaries = sorted(
            {
                now,
                *[at for at, _ in pv + load if now < at <= now + timedelta(hours=48)],
                *[
                    now + timedelta(hours=step / 2)
                    for step in range(1, int(CORRECTION_HOURS * 2) + 1)
                    if result.correction < 1
                ],
            }
        )
        slots = []
        pv_series, load_series = [], []
        for start, end in zip(boundaries, boundaries[1:], strict=False):
            generation, demand = _value_at(pv, start), _value_at(load, start)
            fade = max(0.0, 1 - (start - now).total_seconds() / 3600 / CORRECTION_HOURS)
            factor = 1 - fade * (1 - result.correction)
            if generation is not None:
                pv_series.append((start, end, round(min(limit, generation * factor), 4)))
            if demand is not None:
                load_series.append((start, end, round(demand, 4)))
            if generation is None or demand is None:
                continue  # gaps never become free solar
            surplus = max(
                0.0,
                min(limit, generation * factor) * (1 - settings.forecast_uncertainty)
                - demand * (1 + settings.forecast_uncertainty)
                - settings.forecast_house_margin_kw,
            )
            slots.append(Forecast(start, end, round(surplus, 4)))
        result.slots = tuple(slots)
        result.pv_series, result.load_series = tuple(pv_series), tuple(load_series)
        if not slots:
            raise ValueError("forecast_horizon_unavailable")
        if len(slots) > 576:
            raise ValueError("forecast_series_invalid")
        result.warnings.append("forecast_is_uncertain_net_surplus_not_guaranteed_energy")
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError) as error:
        allowed = {
            "forecast_missing",
            "forecast_stale_or_pre_restart",
            "forecast_unit_invalid",
            "forecast_series_invalid",
            "forecast_horizon_unavailable",
        }
        code = (
            error.args[0]
            if error.args and isinstance(error.args[0], str) and error.args[0] in allowed
            else "forecast_series_invalid"
        )
        result.slots = ()
        result.pv_series = result.load_series = ()
        result.source = "unavailable"
        result.load_basis = None
        result.load_quality = "unavailable"
        result.load_floor_kw = None
        result.pv_error_kw = None
        result.correction = 1.0
        result.warnings.append(code)
    return result
