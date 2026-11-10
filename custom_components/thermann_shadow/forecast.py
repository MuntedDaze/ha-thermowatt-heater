"""Bounded read-only adapters for published HA forecast attributes, never HTTP."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .model import Forecast, Settings, number, timestamp


@dataclass
class ForecastResult:
    slots: tuple[Forecast, ...] = ()
    source: str = "disabled"
    age_minutes: float | None = None
    pv_error_kw: float | None = None
    correction: float = 1.0
    warnings: list[str] = field(default_factory=list)


def _series(state, kind: str, now: datetime, boot: datetime, settings: Settings):
    if state is None or state.attributes.get("restored") or state.state == "unavailable":
        raise ValueError("forecast_missing")
    # last_reported alone is NOT forecast generation time: EMHASS may republish
    # an old plan. Require explicit provenance on a small owner template sensor.
    generated = timestamp(state.attributes.get("forecast_generated_at"))
    age = (now - generated).total_seconds() / 60
    if generated < boot or not 0 <= age <= settings.forecast_max_age_minutes:
        raise ValueError("forecast_stale_or_pre_restart")
    unit = state.attributes.get("unit_of_measurement")
    if unit not in {"W", "kW"}:
        raise ValueError("forecast_unit_invalid")
    raw = state.attributes.get("forecasts")
    key = "p_pv_forecast" if kind == "pv" else "p_load_forecast"
    if kind == "pv" and isinstance(state.attributes.get("watts"), Mapping):
        raw = [{"date": at, key: value} for at, value in state.attributes["watts"].items()]
        unit = "W"  # official Forecast.Solar watts response, never Wh/kWh
    if not isinstance(raw, (list, tuple)) or not 2 <= len(raw) <= 577:
        raise ValueError("forecast_series_invalid")
    points = []
    for row in raw:
        if not isinstance(row, Mapping):
            raise ValueError("forecast_series_invalid")
        at, value = timestamp(row.get("date")), number(row.get(key))
        value /= 1000 if unit == "W" else 1
        if not 0 <= value <= 30 or (points and at <= points[-1][0]):
            raise ValueError("forecast_series_invalid")
        points.append((at, value))
    # The last timestamp is an end boundary, not an indefinitely held prediction.
    if points[-1][0] > now + timedelta(hours=48) or any(
        (b[0] - a[0]).total_seconds() > 7200 for a, b in zip(points, points[1:], strict=False)
    ):
        raise ValueError("forecast_series_invalid")
    return points, age


def build_forecast(now, boot, settings, pv_state, load_state, measured_pv=None):
    result = ForecastResult()
    if not settings.forecast_enabled:
        return result
    try:
        pv, pv_age = _series(pv_state, "pv", now, boot, settings)
        load, load_age = _series(load_state, "load", now, boot, settings)
        result.age_minutes = max(pv_age, load_age)
        result.source = "published_pv_and_house_load"
        expected = next(
            (a[1] for a, b in zip(pv, pv[1:], strict=False) if a[0] <= now < b[0]), None
        )
        if expected is not None and measured_pv is not None and expected > 0.1:
            result.pv_error_kw = round(measured_pv - expected, 3)
            result.correction = min(1.0, max(0.0, measured_pv / expected))
        boundaries = sorted({now, *[at for at, _ in pv + load if at > now]})
        slots = []
        for start, end in zip(boundaries, boundaries[1:], strict=False):
            generation = next(
                (a[1] for a, b in zip(pv, pv[1:], strict=False) if a[0] <= start < b[0]), None
            )
            demand = next(
                (a[1] for a, b in zip(load, load[1:], strict=False) if a[0] <= start < b[0]), None
            )
            if generation is None or demand is None:
                continue  # gaps never become free solar
            surplus = max(
                0.0,
                generation * result.correction * (1 - settings.forecast_uncertainty)
                - demand * (1 + settings.forecast_uncertainty)
                - settings.forecast_house_margin_kw,
            )
            slots.append(Forecast(start, end, surplus))
        result.slots = tuple(slots)
        if not slots:
            raise ValueError("forecast_horizon_unavailable")
        if len(slots) > 576:
            raise ValueError("forecast_series_invalid")
        result.warnings.append("forecast_is_uncertain_net_surplus_not_guaranteed_energy")
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        allowed = {
            "forecast_missing",
            "forecast_stale_or_pre_restart",
            "forecast_unit_invalid",
            "forecast_series_invalid",
            "forecast_horizon_unavailable",
        }
        code = (
            error.args[0] if error.args and error.args[0] in allowed else "forecast_series_invalid"
        )
        result.slots = ()
        result.source = "unavailable"
        result.warnings.append(code)
    return result
