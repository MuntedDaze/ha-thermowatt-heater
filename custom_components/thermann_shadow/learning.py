"""Robust, time-held-out learning gate. No I/O or automatic commissioning."""

from datetime import datetime, timedelta
import math
from statistics import median


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def moment(value):
    try:
        at = datetime.fromisoformat(value)
        return at if at.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def evaluate(rows, target, litres, nominal_kw, identity, now):
    nominal = nominal_kw / (litres * 4.186 / 3600)
    result = {
        "model_version": 1,
        "target_c": target,
        "sessions": 0,
        "days": 0,
        "training_sessions": 0,
        "heldout_sessions": 0,
        "heldout_days": 0,
        "eligible": False,
        "reason": "insufficient_clean_independent_sessions",
        "nominal_c_per_hour": nominal,
        "conservative_c_per_hour": nominal,
        "heldout_mae_minutes": None,
        "heldout_p90_relative_error": None,
        "conservative_coverage": None,
        "thermal_loss_identified": False,
        "extra_storage_usefulness": "unidentified_without_independent_demand_evidence",
    }
    clean = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        end, start = moment(row.get("at")), moment(row.get("started_at"))
        if (
            type(row.get("model_version")) is not int
            or row.get("model_version") != 1
            or row.get("complete_start") is not True
            or row.get("quality") != "clean_covered_fit"
            or row.get("possible_draw") is not False
            or row.get("target_c") != target
            or row.get("tank_litres") != litres
            or row.get("nominal_kw") != nominal_kw
            or row.get("meter_identity") != identity
            or not identity
            or end is None
            or start is None
            or not start < end <= now
            or now - end > timedelta(days=30)
            or not all(
                number(row.get(k)) and row[k] > 0
                for k in ("fit_rise_c", "fit_hours", "fit_energy_kwh")
            )
        ):
            continue
        rate = row["fit_rise_c"] / row["fit_hours"]
        if not 0.5 * nominal <= rate <= 1.5 * nominal:
            continue
        clean[(start.isoformat(), end.isoformat())] = {**row, "end": end, "rate": rate}
    ordered = sorted(clean.values(), key=lambda r: r["end"])
    days = sorted({r["end"].date() for r in ordered})
    result.update(sessions=len(ordered), days=len(days))
    if len(ordered) < 20 or len(days) < 5:
        return result
    hold_days = set(days[-max(2, math.ceil(len(days) * 0.3)) :])
    train = [r for r in ordered if r["end"].date() not in hold_days]
    held = [r for r in ordered if r["end"].date() in hold_days]
    result.update(
        training_sessions=len(train), heldout_sessions=len(held), heldout_days=len(hold_days)
    )
    if len(train) < 10 or len(held) < 5:
        result["reason"] = "insufficient_independent_heldout_days"
        return result
    rates = sorted(r["rate"] for r in train)
    fitted = median(rates)
    # Lower observed quantile with a 5% reserve; never faster than nominal.
    lower = min(nominal, rates[max(0, math.floor(len(rates) * 0.1) - 1)] * 0.95)
    errors, relative, covered = [], [], 0
    for row in held:
        actual = row["fit_hours"] * 60
        predicted = row["fit_rise_c"] / fitted * 60
        errors.append(abs(predicted - actual))
        relative.append(abs(predicted - actual) / actual)
        covered += row["fit_rise_c"] / lower * 60 >= actual
    p90 = sorted(relative)[min(len(relative) - 1, math.ceil(0.9 * len(relative)) - 1)]
    result.update(
        fitted_c_per_hour=fitted,
        rate_mad_c_per_hour=median(abs(rate - fitted) for rate in rates),
        conservative_c_per_hour=lower,
        heldout_mae_minutes=sum(errors) / len(errors),
        heldout_p90_relative_error=p90,
        conservative_coverage=covered / len(held),
    )
    result["eligible"] = (
        result["heldout_mae_minutes"] <= 15 and p90 <= 0.25 and covered / len(held) >= 0.9
    )
    result["reason"] = (
        "heldout_validated_requires_hardware_gate"
        if result["eligible"]
        else "heldout_error_or_coverage_failed"
    )
    return result


def planning(metrics, enabled, qualified, verified, persistent=True):
    nominal = metrics["nominal_c_per_hour"]
    if not enabled:
        return nominal, "nominal_learning_disabled"
    if not qualified:
        return nominal, "nominal_hardware_unqualified"
    if not verified:
        return nominal, "nominal_circuit_unavailable"
    if not persistent:
        return nominal, "nominal_history_not_persistent"
    if not metrics["eligible"]:
        return nominal, "nominal_" + metrics["reason"]
    return min(nominal, metrics["conservative_c_per_hour"]), "learned_conservative_lower_bound"
