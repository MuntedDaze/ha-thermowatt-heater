"""One metadata catalogue for native controls, forms, defaults and validation."""

from dataclasses import dataclass

from .config import DEFAULT_OPTIONS


@dataclass(frozen=True)
class Setting:
    name: str
    group: str
    explanation: str
    low: float = 0
    high: float = 1
    unit: str | None = None
    choices: tuple[str, ...] = ()
    kind: str = "number"


CATALOG = {
    "morning_threshold_c": Setting(
        "Morning comfort threshold",
        "Comfort",
        "Bottom-sensor decision threshold; NEVER a heater setpoint or hygiene temperature.",
        30,
        60,
        "°C",
    ),
    "morning_time": Setting(
        "Morning deadline",
        "Comfort",
        "Hobart local time, independent of tariff boundaries; before noon.",
        kind="time",
    ),
    "target_c": Setting(
        "Afternoon storage target",
        "Comfort",
        "Selected model target is never silently reduced. 65–70°C is a planning range, not a newly qualified command limit.",
        65,
        70,
        "°C",
    ),
    "evening_time": Setting(
        "Afternoon comfort preference",
        "Comfort",
        "Hobart local. Weekday storage deadline follows actual evening tariff peak; this preference remains visible separately.",
        kind="time",
    ),
    "margin_minutes": Setting(
        "Heating time allowance",
        "Comfort",
        "Extra full-power model minutes when heat is required. Uncalibrated; comfort overrides optional dwell.",
        0,
        120,
        "min",
    ),
    "min_solar_kw": Setting(
        "Minimum useful net surplus",
        "Solar & Forecasting",
        "Partial solar can be worthwhile. Economic comparison must also pass; never a variable-power command.",
        0,
        3,
        "kW",
    ),
    "export_headroom_kw": Setting(
        "Solar headroom",
        "Solar & Forecasting",
        "Deduct from measured surplus for uncertain household loads.",
        0,
        3,
        "kW",
    ),
    "forecast_enabled": Setting(
        "Use published forecasts",
        "Solar & Forecasting",
        "Optional local PV AND household-load forecasts with generation timestamps; missing forecasts never delay fallback.",
        kind="switch",
    ),
    "forecast_uncertainty": Setting(
        "Forecast uncertainty margin",
        "Solar & Forecasting",
        "Fraction: reduce PV and increase household load. 0.25 means 25%; never guaranteed surplus.",
        0,
        0.9,
    ),
    "forecast_house_margin_kw": Setting(
        "Extra forecast household load",
        "Solar & Forecasting",
        "Additional allowance for competing appliances, beyond forecast demand.",
        0,
        5,
        "kW",
    ),
    "solar_hold_minutes": Setting(
        "Solar start qualification",
        "Heating Cycles",
        "Sustained economic advantage on fresh observations before a SIMULATED optional start.",
        5,
        30,
        "min",
    ),
    "solar_loss_minutes": Setting(
        "Economic loss grace period",
        "Heating Cycles",
        "Sustained cost disadvantage before a SIMULATED optional stop; short clouds do not stop a cycle.",
        0,
        120,
        "min",
    ),
    "minimum_cycle_minutes": Setting(
        "Minimum optional cycle",
        "Heating Cycles",
        "SIMULATION ONLY. Comfort, data gates, owner intervention and protections override dwell.",
        0,
        180,
        "min",
    ),
    "minimum_gap_minutes": Setting(
        "Minimum optional cycle gap",
        "Heating Cycles",
        "SIMULATION ONLY. Comfort can start sooner. No physical On/resume contract is qualified.",
        0,
        180,
        "min",
    ),
    "switching_benefit_aud": Setting(
        "Minimum economic switching benefit",
        "Heating Cycles",
        "Whole remaining-cycle AUD advantage, not cents/kWh. Experimental $0.10 may deliberately suppress small savings.",
        0,
        5,
        "AUD",
    ),
    "paused": Setting(
        "Pause shadow planning",
        "Advanced",
        "Pauses only hypothetical decisions; native Schedule continues.",
        kind="switch",
    ),
    "meter_verified": Setting(
        "Meter sign and units verified",
        "Advanced",
        "Owner verification, not an optimisation preference. Restore recommendations preserves this flag.",
        kind="switch",
    ),
    "tariff_verified": Setting(
        "Tariff contract verified",
        "Advanced",
        "Owner confirmation of rates, periods and clock. Restore preserves this flag.",
        kind="switch",
    ),
    "import_positive": Setting(
        "Positive grid means import",
        "Advanced",
        "OFF means export-positive HK1000. Never change without a load test; restore preserves direction.",
        kind="switch",
    ),
    "tariff_clock": Setting(
        "Tariff clock",
        "Advanced",
        "Confirmed Aurora 93 uses standard (fixed AEST UTC+10), automatically one hour later in Hobart summer.",
        choices=("standard", "local"),
        kind="select",
    ),
    "tariff_profile": Setting(
        "Tariff periods mode",
        "Advanced",
        "aurora_93 uses editable weekday peak times below; custom retains advanced weekly JSON periods in Configure.",
        choices=("aurora_93", "custom"),
        kind="select",
    ),
    "weekend_peak": Setting(
        "Use peak periods on weekends",
        "Advanced",
        "OFF for confirmed Aurora 93, all weekend off-peak.",
        kind="switch",
    ),
    "off_peak_rate": Setting(
        "Off-peak import price",
        "Advanced",
        "AUD/kWh from your contract; includes all grid energy in the 3kW scenario.",
        -5,
        10,
        "AUD/kWh",
    ),
    "peak_rate": Setting(
        "Peak import price",
        "Advanced",
        "AUD/kWh; actual clock boundaries affect every candidate minute.",
        -5,
        10,
        "AUD/kWh",
    ),
    "shoulder_rate": Setting(
        "Shoulder import price",
        "Advanced",
        "Used only by custom weekly periods with shoulder entries.",
        -5,
        10,
        "AUD/kWh",
    ),
    "feed_in_rate": Setting(
        "Export compensation",
        "Advanced",
        "Foregone feed-in revenue counts as a cost of solar self-consumption.",
        0,
        2,
        "AUD/kWh",
    ),
    "forecast_max_age_minutes": Setting(
        "Maximum forecast generation age",
        "Advanced",
        "Require real generation time; republishing an old forecast does not freshen it.",
        15,
        360,
        "min",
    ),
    "solar_window_minutes": Setting(
        "Recent-export scenario horizon",
        "Advanced",
        "Bounded assumption for current export, never a daily forecast or guaranteed solar.",
        5,
        30,
        "min",
    ),
    "status_max_age_minutes": Setting(
        "Maximum cloud poll age",
        "Advanced",
        "Only local freshness gate; does not alter bridge polling or issue refresh requests.",
        30,
        90,
        "min",
    ),
    "grid_max_age_seconds": Setting(
        "Maximum power reading age",
        "Advanced",
        "Missing/stale observations reset economic holds; no cloud calls.",
        30,
        300,
        "s",
    ),
    "expected_native_target_c": Setting(
        "Expected native target",
        "Advanced",
        "Reference only. Different observed mode/target latches intervention; never sets the heater.",
        20,
        75,
        "°C",
    ),
    "native_schedule_clock": Setting(
        "Native schedule clock reference",
        "Advanced",
        "Reference only; never adjusts the device clock or native Schedule.",
        choices=("local", "standard"),
        kind="select",
    ),
    "native_schedule_clock_verified": Setting(
        "Native clock checked",
        "Advanced",
        "Owner observation only; restore preserves this verification.",
        kind="switch",
    ),
    "t_comfort_reference_c": Setting(
        "T-Comfort reference",
        "Advanced",
        "Reference only; 10°C is not a useful comfort reserve. Never changes T-Comfort.",
        10,
        75,
        "°C",
    ),
    "native_clock_check_date": Setting(
        "Native clock check date",
        "Advanced",
        "Owner check date YYYY-MM-DD, blank if unknown; reference only.",
        kind="text",
    ),
    "tariff_periods": Setting(
        "Custom weekly tariff periods",
        "Advanced",
        "Configure advanced JSON: days 0–6, start/end HH:MM, kind. Used only with custom tariff mode; no YAML editing.",
        kind="form",
    ),
    "native_schedule_periods": Setting(
        "Native schedule reference",
        "Advanced",
        "Reported approximate times in JSON, for comparison only; NEVER changes the heater programme.",
        kind="form",
    ),
}
for key in ("peak_morning_start", "peak_morning_end", "peak_evening_start", "peak_evening_end"):
    CATALOG[key] = Setting(
        key.replace("_", " ").capitalize(),
        "Advanced",
        "Tariff-clock HH:MM, not Hobart comfort time. Must be increasing: morning start/end, evening start/end.",
        kind="time",
    )
assert set(CATALOG) == set(DEFAULT_OPTIONS)

PRESERVE_ON_RESTORE = {
    "meter_verified",
    "tariff_verified",
    "import_positive",
    "expected_native_target_c",
    "native_schedule_periods",
    "native_schedule_clock",
    "native_schedule_clock_verified",
    "native_clock_check_date",
    "t_comfort_reference_c",
}


def recommended_options(current):
    """Only preferences; never rewrite mappings, verification or native references."""
    return {
        **current,
        **{key: value for key, value in DEFAULT_OPTIONS.items() if key not in PRESERVE_ON_RESTORE},
    }
