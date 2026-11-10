"""Shared configuration parsing, independent of Home Assistant."""

import json

from .model import Settings, Tariff, number, validate_tariffs, validate_settings

DOMAIN = "thermann_shadow"
DEFAULT_SOURCES = {
    "heater": "water_heater.home_boiler_home",
    "mode": "sensor.home_boiler_home_vendor_mode",
    "last_poll": "sensor.home_last_successful_poll",
    "cloud_health": "sensor.home_cloud_health",
    "requests": "sensor.home_cloud_request_attempts_local_lifetime",
    "grid": "sensor.goodwe_inverter_meter_active_power",
    "pv": "sensor.goodwe_inverter_pv_power",
    "house": "sensor.goodwe_inverter_house_consumption",
    "import_energy": "sensor.goodwe_inverter_meter_total_energy_import",
    "export_energy": "sensor.goodwe_inverter_meter_total_energy_export",
}
DEFAULT_OPTIONS = {
    "paused": False,
    "meter_verified": False,
    "tariff_verified": False,
    "import_positive": False,  # owner-provided export-positive observation, unqualified
    "tariff_clock": "local",
    "target_c": 65.0,
    "expected_native_target_c": 70.0,
    "margin_minutes": 30.0,
    "feed_in_rate": 0.0,  # unknown contract; never used until tariff_verified
    "off_peak_rate": 0.0,
    "shoulder_rate": 0.0,
    "peak_rate": 0.0,
    "export_headroom_kw": 0.3,
    "status_max_age_minutes": 45.0,
    "grid_max_age_seconds": 120.0,
    "tariff_periods": '[{"days":[0,1,2,3,4,5,6],"start":"00:00","end":"00:00","kind":"off_peak"}]',
    "native_schedule_periods": '[{"days":[0,1,2,3,4],"start":"04:00","end":"08:00"},{"days":[0,1,2,3,4],"start":"11:00","end":"17:00"},{"days":[5,6],"start":"06:00","end":"22:00"}]',
    "native_schedule_clock": "local",
    "native_schedule_clock_verified": False,
    "t_comfort_reference_c": 10.0,
}


def _minute(value):
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        raise ValueError("tariff_time_invalid")
    hour, minute = int(value[:2]), int(value[3:])
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("tariff_time_invalid")
    return hour * 60 + minute


def parse_options(options):
    from .native import parse_native

    values = {**DEFAULT_OPTIONS, **options}
    for key in (
        "paused",
        "meter_verified",
        "tariff_verified",
        "import_positive",
        "native_schedule_clock_verified",
    ):
        if type(values[key]) is not bool:
            raise ValueError("settings_invalid")
    rates = {kind: number(values[f"{kind}_rate"]) for kind in ("off_peak", "shoulder", "peak")}
    if any(not -5 <= rate <= 10 for rate in rates.values()):
        raise ValueError("tariff_invalid")
    raw = values["tariff_periods"]
    if not isinstance(raw, str) or len(raw) > 8192:
        raise ValueError("tariff_invalid")
    periods = json.loads(raw)
    if not isinstance(periods, list) or not 1 <= len(periods) <= 32:
        raise ValueError("tariff_invalid")
    tariffs = []
    for item in periods:
        if not isinstance(item, dict) or set(item) != {"days", "start", "end", "kind"}:
            raise ValueError("tariff_invalid")
        if not isinstance(item["days"], list) or item["kind"] not in rates:
            raise ValueError("tariff_invalid")
        tariffs.append(
            Tariff(
                tuple(item["days"]),
                _minute(item["start"]),
                _minute(item["end"]),
                rates[item["kind"]],
                item["kind"],
            )
        )
    tariffs = tuple(tariffs)
    validate_tariffs(tariffs, values["tariff_clock"])
    settings = Settings(
        **{
            key: values[key]
            if key
            in {"paused", "meter_verified", "tariff_verified", "import_positive", "tariff_clock"}
            else number(values[key])
            for key in Settings.__dataclass_fields__
            if key not in {"morning", "evening"}
        }
    )
    validate_settings(settings)
    parse_native(values["native_schedule_periods"])
    if (
        values["native_schedule_clock"] not in {"local", "standard"}
        or not 10 <= number(values["t_comfort_reference_c"]) <= settings.expected_native_target_c
    ):
        raise ValueError("native_reference_invalid")
    return settings, tariffs
