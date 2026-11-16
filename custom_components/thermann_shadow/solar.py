"""Shared optional-solar timings and explicit CT-free commissioning identity."""

from datetime import timedelta

QUALIFY = timedelta(minutes=10)
WITHDRAW = timedelta(minutes=10)
SPACING = timedelta(minutes=15)
COOLDOWN = SPACING
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
