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
