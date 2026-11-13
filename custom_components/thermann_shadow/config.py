"""Shared configuration parsing, independent of Home Assistant."""

import json
import re
from datetime import time

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
OPTIONAL_SOURCES = {"forecast_pv": "", "forecast_load": "", "pv_ac": "", "heater_power": ""}
# AC-side inverter output, consistent with the AC meter and house load. Used
# when no explicit pv_ac mapping is saved (existing 0.3.0 entries).
DEFAULT_PV_AC = "sensor.goodwe_inverter_total_power"
# Old default morning threshold. A saved value equal to it was never chosen by
# the owner, so the 0.4.0 entry migration moves it to the new 42 °C requirement.
LEGACY_MORNING_THRESHOLD_C = 40.0
DEFAULT_OPTIONS = {
    "paused": False,
    "meter_verified": True,  # owner-reported HK1000 load test; direction preserved
    "tariff_verified": True,  # owner-confirmed Tariff 93, fixed AEST
    "import_positive": False,
    "tariff_clock": "standard",
    "target_c": 70.0,
    "morning_threshold_c": 42.0,
    "morning_preferred_c": 45.0,
    "expected_native_target_c": 70.0,
    "margin_minutes": 30.0,
    "feed_in_rate": 0.092760,
    "off_peak_rate": 0.170200,
    "shoulder_rate": 0.170200,
    "peak_rate": 0.361878,
    "export_headroom_kw": 0.3,
    "status_max_age_minutes": 45.0,
    "grid_max_age_seconds": 120.0,
    "solar_hold_minutes": 10.0,
    "solar_window_minutes": 15.0,
    "min_solar_kw": 0.1,
    "switching_benefit_aud": 0.10,
    "solar_loss_minutes": 20.0,
    "minimum_cycle_minutes": 30.0,
    "minimum_gap_minutes": 30.0,
    "forecast_enabled": False,
    "forecast_uncertainty": 0.25,
    "forecast_max_age_minutes": 120.0,
    "forecast_house_margin_kw": 0.3,
    # Weekday deadlines follow the tariff's actual peak starts. These household
    # times apply when a day has no peak (weekends) or the tariff is unverified.
    "morning_time": "08:00",
    "evening_time": "16:00",
    "shower_time_enabled": False,
    "shower_time": "07:00",
    # 0.7.0: morning comfort every day (Hobart local).
    "morning_preferred_time": "06:00",
    "morning_hard_time": "07:00",
    "expected_morning_draw_c": 10.0,
    "standing_loss_c_per_hour": 0.2,
    "wait_benefit_aud_per_kwh": 0.05,
    "pv_ac_limit_kw": 5.0,
    "base_load_source": "measured_only",
    "tariff_profile": "aurora_93",
    "peak_morning_start": "07:00",
    "peak_morning_end": "10:00",
    "peak_evening_start": "16:00",
    "peak_evening_end": "21:00",
    "weekend_peak": False,
    "tariff_periods": '[{"days":[0,1,2,3,4],"start":"00:00","end":"07:00","kind":"off_peak"},{"days":[0,1,2,3,4],"start":"07:00","end":"10:00","kind":"peak"},{"days":[0,1,2,3,4],"start":"10:00","end":"16:00","kind":"off_peak"},{"days":[0,1,2,3,4],"start":"16:00","end":"21:00","kind":"peak"},{"days":[0,1,2,3,4],"start":"21:00","end":"00:00","kind":"off_peak"},{"days":[5,6],"start":"00:00","end":"00:00","kind":"off_peak"}]',
    "native_schedule_periods": '[{"days":[0,1,2,3,4],"start":"04:00","end":"08:00"},{"days":[0,1,2,3,4],"start":"11:00","end":"17:00"},{"days":[5,6],"start":"06:00","end":"22:00"}]',
    "native_schedule_clock": "local",
    "native_schedule_clock_verified": False,
    "native_clock_check_date": "",
    "t_comfort_reference_c": 10.0,
    # Production controller. A fresh install CANNOT command: no topic, no T3
    # qualification, and the master switch (stored with the controller state,
    # not here) defaults to OFF. (0.6.0 removed the empty-Schedule confirmation.)
    "controller_command_topic": "",
    "controller_bridge_qualified": False,
    # 0.9.0: ON only after the supervised bridge 1.3.13 three-state qualification.
    "controller_three_state_qualified": False,
    "controller_min_heating_minutes": 30.0,
    "controller_min_rest_minutes": 30.0,
    "controller_max_commands_per_day": 6.0,
    "controller_confirmation_timeout_minutes": 65.0,
    "controller_max_requests_per_day": 220.0,
    "controller_execution_latency_minutes": 30.0,
    "controller_notify_service": "",
}
# 0.7.1 (settings audit): ranges a saved value must respect. Values saved by
# older versions outside them are brought inside once, by the entry migration
# (see __init__.async_migrate_entry), and the change is logged.
RANGES_0_7_1 = {
    "status_max_age_minutes": (35.0, 90.0),  # F7: 30 flaps with 30-minute polling
    "forecast_max_age_minutes": (35.0, 360.0),  # F8: EMHASS publishes every 30 min
    "off_peak_rate": (0.0, 2.0),
    "shoulder_rate": (0.0, 2.0),
    "peak_rate": (0.0, 2.0),
}
WHOLE_NUMBER_OPTIONS = ("controller_max_commands_per_day", "controller_max_requests_per_day")
# F6: a rest longer than the latency reserve + this could delay a comfort start
# beyond what the planner reserves.
REST_BEYOND_LATENCY_MINUTES = 30.0
NOTIFY_SERVICE_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")
# Readable reasons for rejected settings (ValueError codes from parse_options).
REJECTION_MESSAGES = {
    "settings_invalid": "A value is outside its allowed range.",
    "morning_preferred_below_minimum": "The morning preferred reserve cannot be below the morning minimum.",
    "morning_times_order": "Morning times must be before noon, with the preferred time not after the hard deadline.",
    "afternoon_time_invalid": "The weekend afternoon ready time must be after noon.",
    "rest_longer_than_latency_reserve": "The minimum rest period can be at most the execution latency reserve plus 30 minutes; a longer rest could delay a comfort start beyond what the planner reserves.",
    "whole_number_required": "Command and cloud-request budgets must be whole numbers.",
    "notify_service_invalid": "Notification service: enter the service name only, for example mobile_app_phone (lower-case letters, digits and _; no 'notify.' in front).",
    "controller_setting_out_of_range": "A controller setting is outside its allowed range.",
    "controller_setting_invalid": "Command topic or notification service is too long or not text.",
    "tariff_invalid": "Tariff prices must be between 0 and 2 $/kWh and custom periods must be valid.",
    "tariff_times_must_increase": "Peak times must increase: morning start, morning end, evening start, evening end.",
    "tariff_time_invalid": "A time is not a valid HH:MM.",
    "native_clock_date_invalid": "The native clock check date must be YYYY-MM-DD or blank.",
    "native_reference_invalid": "The T-Comfort reference must not exceed the expected native target.",
}


def rejection_message(error: Exception) -> str:
    code = error.args[0] if error.args and isinstance(error.args[0], str) else ""
    return REJECTION_MESSAGES.get(code, "The settings are not valid together.")


CONTROLLER_BOUNDS = {
    "controller_min_heating_minutes": (30, 180),
    "controller_min_rest_minutes": (30, 90),
    "controller_max_commands_per_day": (4, 10),
    "controller_confirmation_timeout_minutes": (35, 120),
    "controller_max_requests_per_day": (160, 400),
    "controller_execution_latency_minutes": (0, 60),
}


def _minute(value):
    if isinstance(value, str) and len(value) == 8 and value.endswith(":00"):
        value = value[:5]
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        raise ValueError("tariff_time_invalid")
    hour, minute = int(value[:2]), int(value[3:])
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("tariff_time_invalid")
    return hour * 60 + minute


def _periods(raw, rates, clock):
    """Parse and fully validate one weekly tariff table (gap- and overlap-free)."""
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
    result = tuple(tariffs)
    validate_tariffs(result, clock)
    return result


def parse_options(options):
    from .native import parse_native

    values = {**DEFAULT_OPTIONS, **options}
    for key in (
        "paused",
        "meter_verified",
        "tariff_verified",
        "import_positive",
        "native_schedule_clock_verified",
        "forecast_enabled",
        "weekend_peak",
        "shower_time_enabled",
        "controller_bridge_qualified",
        "controller_three_state_qualified",
    ):
        if type(values[key]) is not bool:
            raise ValueError("settings_invalid")
    for key, (low, high) in CONTROLLER_BOUNDS.items():
        if not low <= number(values[key]) <= high:
            raise ValueError("controller_setting_out_of_range")
    for key in ("controller_command_topic", "controller_notify_service"):
        if not isinstance(values[key], str) or len(values[key]) > 64:
            raise ValueError("controller_setting_invalid")
    notify = values["controller_notify_service"].strip()
    if notify and not NOTIFY_SERVICE_PATTERN.match(notify):
        raise ValueError("notify_service_invalid")  # F4: was silently ignored
    for key in WHOLE_NUMBER_OPTIONS:
        if number(values[key]) != int(number(values[key])):
            raise ValueError("whole_number_required")  # F10
    if number(values["controller_min_rest_minutes"]) > (
        number(values["controller_execution_latency_minutes"]) + REST_BEYOND_LATENCY_MINUTES
    ):
        raise ValueError("rest_longer_than_latency_reserve")  # F6
    for key, (low, high) in RANGES_0_7_1.items():
        if not low <= number(values[key]) <= high:
            raise ValueError("tariff_invalid" if key.endswith("_rate") else "settings_invalid")
    rates = {kind: number(values[f"{kind}_rate"]) for kind in ("off_peak", "shoulder", "peak")}
    profile = values["tariff_profile"]
    if (
        "tariff_profile" not in options
        and values["tariff_periods"] != DEFAULT_OPTIONS["tariff_periods"]
    ):
        profile = "custom"
    if profile not in {"aurora_93", "custom"}:
        raise ValueError("tariff_invalid")
    raw = values["tariff_periods"]
    # The stored custom weekly table is ALWAYS validated, even while the Aurora
    # profile is active. It is persisted, and switching the profile select later
    # must never activate an unvalidated table. One invalid field saves nothing.
    _periods(raw, rates, values["tariff_clock"])
    if profile == "aurora_93":
        edges = [
            "00:00",
            *[
                values[key]
                for key in (
                    "peak_morning_start",
                    "peak_morning_end",
                    "peak_evening_start",
                    "peak_evening_end",
                )
            ],
            "00:00",
        ]
        minutes = [_minute(v) for v in edges[:-1]] + [1440]
        if any(a >= b for a, b in zip(minutes, minutes[1:], strict=False)):
            raise ValueError("tariff_times_must_increase")
        raw = json.dumps(
            [
                {
                    "days": list(range(7 if values["weekend_peak"] else 5)),
                    "start": a,
                    "end": b,
                    "kind": "peak" if index % 2 else "off_peak",
                }
                for index, (a, b) in enumerate(zip(edges, edges[1:], strict=False))
            ]
            + (
                []
                if values["weekend_peak"]
                else [{"days": [5, 6], "start": "00:00", "end": "00:00", "kind": "off_peak"}]
            )
        )
    tariffs = _periods(raw, rates, values["tariff_clock"])
    settings = Settings(
        **{
            key: values[key]
            if key
            in {
                "paused",
                "meter_verified",
                "tariff_verified",
                "import_positive",
                "tariff_clock",
                "forecast_enabled",
                "shower_time_enabled",
                "base_load_source",
            }
            else number(values[key])
            for key in Settings.__dataclass_fields__
            if key not in {"morning", "evening", "shower_time", "morning_preferred", "morning_hard"}
        },
        morning=time(*divmod(_minute(values["morning_time"]), 60)),
        evening=time(*divmod(_minute(values["evening_time"]), 60)),
        shower_time=time(*divmod(_minute(values["shower_time"]), 60)),
        morning_preferred=time(*divmod(_minute(values["morning_preferred_time"]), 60)),
        morning_hard=time(*divmod(_minute(values["morning_hard_time"]), 60)),
    )
    # Cross-field checks first, so the owner sees WHICH rule failed.
    if not settings.morning_threshold_c <= settings.morning_preferred_c:
        raise ValueError("morning_preferred_below_minimum")
    if not time(0) <= settings.morning_preferred <= settings.morning_hard <= time(11, 59):
        raise ValueError("morning_times_order")
    if not time(12) <= settings.evening <= time(23, 59):
        raise ValueError("afternoon_time_invalid")
    validate_settings(settings)
    from datetime import date

    checked = values["native_clock_check_date"]
    if not isinstance(checked, str) or (
        checked and date.fromisoformat(checked).isoformat() != checked
    ):
        raise ValueError("native_clock_date_invalid")
    parse_native(values["native_schedule_periods"])
    if (
        values["native_schedule_clock"] not in {"local", "standard"}
        or not 10 <= number(values["t_comfort_reference_c"]) <= settings.expected_native_target_c
    ):
        raise ValueError("native_reference_invalid")
    return settings, tariffs


def migrate_0_7_1(options):
    """Bring values saved by older versions inside the 0.7.1 ranges.

    Returns (options, {key: (old, new)}). Only values that 0.7.1 would reject
    are changed, each to the nearest allowed value; nothing else is touched.
    Without this an entry with such a value could not load after the upgrade."""
    result = dict(options)
    changes = {}

    def put(key, new):
        old = result.get(key, DEFAULT_OPTIONS[key])
        if old != new:
            changes[key] = (old, new)
            result[key] = new

    for key, (low, high) in RANGES_0_7_1.items():
        if key in result:
            try:
                value = number(result[key])
            except (TypeError, ValueError, OverflowError):
                continue
            put(key, min(high, max(low, value)))
    for key in WHOLE_NUMBER_OPTIONS:
        if key in result:
            try:
                value = number(result[key])
            except (TypeError, ValueError, OverflowError):
                continue
            put(key, float(int(value)))
    try:
        latency = number(
            result.get(
                "controller_execution_latency_minutes",
                DEFAULT_OPTIONS["controller_execution_latency_minutes"],
            )
        )
        rest = number(
            result.get(
                "controller_min_rest_minutes", DEFAULT_OPTIONS["controller_min_rest_minutes"]
            )
        )
    except (TypeError, ValueError, OverflowError):
        pass
    else:
        limit = min(
            CONTROLLER_BOUNDS["controller_min_rest_minutes"][1],
            latency + REST_BEYOND_LATENCY_MINUTES,
        )
        if rest > limit:
            put(
                "controller_min_rest_minutes",
                float(max(CONTROLLER_BOUNDS["controller_min_rest_minutes"][0], limit)),
            )
    notify = result.get("controller_notify_service")
    if (
        isinstance(notify, str)
        and notify.strip()
        and not NOTIFY_SERVICE_PATTERN.match(notify.strip())
    ):
        name = notify.strip()
        name = name[len("notify.") :] if name.startswith("notify.") else name
        put("controller_notify_service", name if NOTIFY_SERVICE_PATTERN.match(name) else "")
    return result, changes


def saved_options(options):
    """Merge defaults while preserving legacy custom tariff periods and overrides."""
    values = {**DEFAULT_OPTIONS, **options}
    if (
        "tariff_profile" not in options
        and values["tariff_periods"] != DEFAULT_OPTIONS["tariff_periods"]
    ):
        values["tariff_profile"] = "custom"
    return values
