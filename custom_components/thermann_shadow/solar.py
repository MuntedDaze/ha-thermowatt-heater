"""Shared optional-solar timings and explicit CT-free commissioning identity."""

from datetime import timedelta

QUALIFY = timedelta(minutes=10)
WITHDRAW = timedelta(minutes=10)
SPACING = timedelta(minutes=15)
COOLDOWN = timedelta(minutes=10)
IMPORT_TOLERANCE_KW = 0.2
PROTECTIVE_REASONS = frozenset(
    {
        "peak_solar_withdrawn",
        "peak_meter_unavailable",
        "peak_heater_meter_unavailable",
        "peak_lockout",
        "peak_solar_uneconomic",
        "peak_solar_no_useful_heat",
        "peak_no_qualified_session",
        "peak_ahead_no_qualified_solar",
    }
)
WITHDRAWAL_REASONS = PROTECTIVE_REASONS | {
    "weekday_solar_boost_withdrawn",
    "solar_opportunity_import",
    "solar_opportunity_ended",
}


def ct_free_record(entity, unit, import_positive, element_kw):
    """A saved record must match this installation; it never proves element ON."""
    if not entity or unit not in {"W", "kW"}:
        return None
    direction = "import_positive" if import_positive else "export_positive"
    return f"{entity}|{unit}|{direction}|{element_kw:g}"


def grid_sanity(grid_import_kw, pv_ac_kw, house_kw, inverter_limit_kw):
    """Measured whole-house consistency only. Never credits nominal heater power."""
    import math

    values = (grid_import_kw, pv_ac_kw, house_kw, inverter_limit_kw)
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        return "fresh_grid_inverter_and_house_readings_required"
    if not 0 <= pv_ac_kw <= inverter_limit_kw * 1.10 or house_kw < 0:
        return "inverter_or_house_reading_implausible"
    if -grid_import_kw > pv_ac_kw + 0.3:
        return "export_exceeds_measured_inverter_output"
    if abs(pv_ac_kw - house_kw + grid_import_kw) > max(0.6, inverter_limit_kw * 0.15):
        return "grid_sign_or_whole_house_balance_inconsistent"
    return "consistent_measured_site_power"
