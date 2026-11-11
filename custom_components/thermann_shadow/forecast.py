"""Bounded read-only adapters for published HA forecast attributes, never HTTP."""

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
    if kind == "pv" and isinstance(state.attributes.get("watts"), Mapping):
        # forecast_solar.get_forecast response: watts keyed by period START.
        raw = [{"date": at, key: value} for at, value in state.attributes["watts"].items()]
        unit = "W"  # official Forecast.Solar watts mapping, never Wh/kWh
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


def _flat_load(state, now: datetime, boot: datetime, settings: Settings) -> float:
    """A measured household baseline, e.g. a Statistics helper mean of house load.

    It is not a forecast, so it has no forecast_generated_at; freshness is the
    helper's own report time. It applies flat across the horizon (no daily shape).
    """
    _available(state)
    reported = state.last_reported
    if (
        reported is None
        or reported < boot
        or not 0 <= (now - reported).total_seconds() / 60 <= settings.forecast_max_age_minutes
    ):
        raise ValueError("forecast_stale_or_pre_restart")
    unit = state.attributes.get("unit_of_measurement")
    if unit not in {"W", "kW"}:
        raise ValueError("forecast_unit_invalid")
    value = number(state.state) / (1000 if unit == "W" else 1)
    if not 0 <= value <= 30:
        raise ValueError("forecast_series_invalid")
    return value


def _value_at(points, at):
    """Step-held value over [a, b); None in a gap or outside the series."""
    for a, b in zip(points, points[1:], strict=False):
        if a[0] <= at < b[0]:
            return a[1] if (b[0] - a[0]).total_seconds() <= MAX_POINT_GAP_SECONDS else None
    return None


def build_forecast(now, boot, settings, pv_state, load_state, measured_pv=None):
    result = ForecastResult()
    if not settings.forecast_enabled:
        return result
    try:
        pv, pv_age = _series(pv_state, "pv", now, boot, settings)
        if load_state is not None and "forecasts" not in load_state.attributes:
            flat = _flat_load(load_state, now, boot, settings)
            load = [(now + timedelta(hours=hour), flat) for hour in range(49)]
            load_age = (now - load_state.last_reported).total_seconds() / 60
            result.load_basis = "flat_measured_household_baseline"
        else:
            load, load_age = _series(load_state, "load", now, boot, settings)
            result.load_basis = "published_household_load_forecast"
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
        if result.load_basis == "flat_measured_household_baseline":
            result.warnings.append("household_load_is_flat_baseline_not_daily_profile")
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
        result.pv_error_kw = None
        result.correction = 1.0
        result.warnings.append(code)
    return result
