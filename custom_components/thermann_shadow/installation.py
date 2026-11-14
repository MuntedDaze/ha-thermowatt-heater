"""Preserve old implicit household facts; new installations verify their own.

Only config-entry migration calls this function. Never used as fresh defaults.
No credentials, authentication generation or bridge options are involved.
"""

from .config import DEFAULT_PV_AC

LEGACY_FACTS = {
    "meter_verified": True,
    "tariff_verified": True,
    "import_positive": False,
    "tariff_clock": "standard",
    "time_zone": "Australia/Hobart",
}


def fresh_options(zone):
    """No household authority or retailer assumptions on an actual fresh setup."""
    return {
        "time_zone": zone,
        "tariff_clock": "local",
        "tariff_profile": "flat",
        "off_peak_rate": 0.0,
        "peak_rate": 0.0,
        "shoulder_rate": 0.0,
        "feed_in_rate": 0.0,
        "meter_verified": False,
        "tariff_verified": False,
        "forecast_enabled": False,
        "optional_solar_boost": False,
        "baseline_c": "62",
        "normal_storage_c": "62",
        "solar_boost_c": "70",
    }


def preserve_existing(options, sources):
    result = {**LEGACY_FACTS, **options}
    mapped = dict(options.get("sources", sources))
    mapped.setdefault("pv_ac", DEFAULT_PV_AC)
    result["sources"] = mapped
    # Previously optional peak heating already needed a commissioned raw CT.
    # No CT never gains optional peak authority during migration.
    raw = mapped.get("heater_power")
    verified = bool(raw and str(options.get("heater_meter_verification", "")).startswith(raw + "|"))
    result.setdefault(
        "peak_heating_policy",
        "Verified solar-only heating" if verified else "Never schedule heating during peak",
    )
    return result
