"""Shared configuration parsing, independent of Home Assistant."""

import json
import re

from .model import Settings, Tariff, number, validate_tariffs, validate_settings
from .solar import SOLAR_START_HEADROOM_KW

DOMAIN = "thermann_shadow"
# Legacy IDs remain solely for migration and documented household examples.
CLOUD_SOURCES = frozenset({"heater", "mode", "last_poll", "cloud_health", "requests"})
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
OPTIONAL_SOURCES = {
    "forecast_pv": "",
    "forecast_load": "",
    "pv_ac": "",
    "heater_power": "",
    "heater_energy": "",
}
# AC-side inverter output, consistent with the AC meter and house load. Used
# when no explicit pv_ac mapping is saved (existing 0.3.0 entries).
DEFAULT_PV_AC = "sensor.goodwe_inverter_total_power"
DEFAULT_OPTIONS = {
    "weekend_solar_heating": True,
    "weekend_pv_start_kw": 0.5,
    "weekend_end_time": "18:00",
    "solar_cooldown_minutes": 10.0,
    "pre_peak_observation_minutes": 30.0,
    "peak_command_lead_minutes": 2.0,
    "low_water_warning_c": 35.0,
    "meter_verified": False,
    "tariff_verified": False,
    "import_positive": True,
    "tariff_clock": "local",
    "time_zone": "Australia/Hobart",  # preserved legacy fallback, not fresh setup
    "daytime_start": "09:00",
    "storage_ready_time": "16:00",
    "baseline_start": "21:00",
    "feed_in_rate": 0.092760,
    "off_peak_rate": 0.170200,
    "shoulder_rate": 0.170200,
    "peak_rate": 0.361878,
    "status_max_age_minutes": 45.0,
    "grid_max_age_seconds": 120.0,
    "forecast_enabled": False,
    "forecast_uncertainty": 0.25,
    "forecast_max_age_minutes": 120.0,
    "forecast_house_margin_kw": 0.3,
    "pv_ac_limit_kw": 5.0,
    "tariff_profile": "aurora_93",
    "peak_morning_start": "07:00",
    "peak_morning_end": "10:00",
    "peak_evening_start": "16:00",
    "peak_evening_end": "21:00",
    "weekend_peak": False,
    "tariff_periods": '[{"days":[0,1,2,3,4],"start":"00:00","end":"07:00","kind":"off_peak"},{"days":[0,1,2,3,4],"start":"07:00","end":"10:00","kind":"peak"},{"days":[0,1,2,3,4],"start":"10:00","end":"16:00","kind":"off_peak"},{"days":[0,1,2,3,4],"start":"16:00","end":"21:00","kind":"peak"},{"days":[0,1,2,3,4],"start":"21:00","end":"00:00","kind":"off_peak"},{"days":[5,6],"start":"00:00","end":"00:00","kind":"off_peak"}]',
    "controller_command_topic": "",
    "controller_max_commands_per_day": 6.0,
    "controller_confirmation_timeout_minutes": 65.0,
    "controller_max_requests_per_day": 220.0,
    "controller_notify_service": "",
    "heater_meter_verification": "",  # commissioned entity_id|W (or |kW); no default authority
    "ct_free_solar_verification": "",  # separate supervised grid-only commissioning record
    "learned_planning_enabled": False,
    "learning_hardware_qualified": False,
    "optional_heat_margin_aud_per_kwh": 0.02,
    "pause_min_saving_aud": 0.30,
    "baseline_c": "45",
    "normal_storage_c": "62",
    "solar_boost_c": "70",
    "tank_litres": 315.0,
    "element_kw": 3.0,
    "completion_margin_minutes": 30.0,
    "optional_solar_boost": True,
    "peak_heating_policy": "Never schedule heating during peak",
    "boost_useful_fraction": 0.9,
    "boost_min_saving_aud": 0.10,
    "controller_four_state_qualified": False,
}
# Settings retired from active use (0.8.0-0.18.0). Nothing reads them. The 1.6
# entry migration (0.18.0) moves any stored value, unchanged, into the
# RETIRED_RECORD dictionary so it stays available for a rollback or an audit but
# can never be read, validated or shown as a current setting again. Their
# former entities are removed from the registry at setup (__init__.py).
# docs/OPERATING_POLICY.md section 1.1 lists what each group was replaced by.
RETIRED_OPTIONS = frozenset(
    {
        # 0.7.0 morning reserve (45 C by 06:00 / 42 C by 07:00): cancelled 20 Nov 2026.
        "morning_threshold_c",
        "morning_preferred_c",
        "morning_preferred_time",
        "morning_hard_time",
        "morning_time",
        "shower_time_enabled",
        "shower_time",
        "evening_time",
        # 0.4-0.8 economic planner, replaced by the simplified policy (0.9.0).
        "target_c",
        "expected_morning_draw_c",
        "standing_loss_c_per_hour",
        "margin_minutes",
        "min_solar_kw",
        "solar_hold_minutes",
        "solar_loss_minutes",
        "solar_window_minutes",
        "minimum_cycle_minutes",
        "minimum_gap_minutes",
        "switching_benefit_aud",
        "wait_benefit_aud_per_kwh",
        "base_load_source",
        "paused",
        "controller_min_heating_minutes",
        "controller_min_rest_minutes",
        "controller_execution_latency_minutes",
        # Native Schedule / T-Comfort references (shadow era).
        "expected_native_target_c",
        "native_schedule_periods",
        "native_schedule_clock",
        "native_schedule_clock_verified",
        "native_clock_check_date",
        "t_comfort_reference_c",
        # Superseded commissioning acknowledgements (four-state qualification;
        # the 0.5.0 empty-Schedule confirmation was removed in 0.6.0).
        "controller_empty_schedule_confirmed",
        "controller_bridge_qualified",
        "controller_three_state_qualified",
        # Weekend qualification and low-PV early end, replaced in 0.17.0.
        "weekend_qualify_minutes",
        "weekend_sunset_kw",
        "weekend_sunset_minutes",
        # Pre-Smart polling and the controller's own polling choice (0.18.0:
        # the Thermann Hot Water app's polling option is the single control).
        "polling_mode",
        "adaptive_polling_enabled",
        "event_aware_polling_enabled",
        "owner_change_check_minutes",
        "adaptive_polling_shadow",
        "adaptive_poll_heating_minutes",
        "adaptive_poll_stable_minutes",
        # Now the constant solar.SOLAR_START_HEADROOM_KW (an installed value that
        # differs is kept active; see migrate_0_18_0).
        "export_headroom_kw",
    }
)
RETIRED_RECORD = "retired_options"
BACKUP_KEY = "restore_backup"
assert not RETIRED_OPTIONS & set(DEFAULT_OPTIONS)

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
NOTIFY_SERVICE_PATTERN = re.compile(r"^[a-z0-9_]{1,64}$")
# Readable reasons for rejected settings (ValueError codes from parse_options).
REJECTION_MESSAGES = {
    "time_zone_invalid": "Select a valid IANA time zone, such as Australia/Perth.",
    "daytime_times_invalid": "Storage window start must be before ready time, and ready time before the overnight baseline returns.",
    "unsupported_target_roles": "Use only supported 45/62/70 targets, with baseline no higher than normal and normal no higher than solar boost.",
    "dual_storage_settings_invalid": "Check tank capacity (50–500 L), nominal element (2–3.6 kW), completion margin (5–120 minutes), useful-heat fraction (0–1) and the peak policy.",
    "settings_invalid": "A value is outside its allowed range.",
    "completion_margin_not_after_peak_lead": "The heating completion margin must be longer than the minutes reserved for the peak OFF command. Increase the completion margin or shorten the peak command lead; nothing was saved.",
    "whole_number_required": "Command and cloud-request budgets must be whole numbers.",
    "notify_service_invalid": "Notification service: enter the service name only, for example mobile_app_phone (lower-case letters, digits and _; no 'notify.' in front).",
    "controller_setting_out_of_range": "A controller setting is outside its allowed range.",
    "controller_setting_invalid": "Command topic or notification service is too long or not text.",
    "tariff_invalid": "Tariff prices must be between 0 and 2 $/kWh and custom periods must be valid.",
    "tariff_times_must_increase": "Peak times must increase: morning start, morning end, evening start, evening end.",
    "tariff_time_invalid": "A time is not a valid HH:MM.",
}


def rejection_message(error: Exception) -> str:
    code = error.args[0] if error.args and isinstance(error.args[0], str) else ""
    return REJECTION_MESSAGES.get(code, "The settings are not valid together.")


NEXT_RANGES = (
    ("weekend_pv_start_kw", 0.1, 3.6),
    ("solar_cooldown_minutes", 10, 60),
    ("pre_peak_observation_minutes", 5, 60),
    ("peak_command_lead_minutes", 1, 10),
    ("low_water_warning_c", 20, 45),
)

CONTROLLER_BOUNDS = {
    "controller_max_commands_per_day": (4, 10),
    "controller_confirmation_timeout_minutes": (35, 120),
    "controller_max_requests_per_day": (160, 400),
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


def _periods(raw, rates, clock, zone="Australia/Hobart"):
    """Parse and fully validate one weekly tariff table (gap- and overlap-free)."""
    if not isinstance(raw, str) or len(raw) > 8192:
        raise ValueError("tariff_invalid")
    periods = json.loads(raw)
    if not isinstance(periods, list) or not 1 <= len(periods) <= 32:
        raise ValueError("tariff_invalid")
    tariffs = []
    for item in periods:
        if (
            not isinstance(item, dict)
            or not {"days", "start", "end", "kind"} <= set(item)
            or set(item) - {"days", "start", "end", "kind", "months", "rate"}
        ):
            raise ValueError("tariff_invalid")
        if not isinstance(item["days"], list) or item["kind"] not in rates:
            raise ValueError("tariff_invalid")
        rate = number(item.get("rate", rates[item["kind"]]))
        if not 0 <= rate <= 2:
            raise ValueError("tariff_invalid")
        tariffs.append(
            Tariff(
                tuple(item["days"]),
                _minute(item["start"]),
                _minute(item["end"]),
                rate,
                item["kind"],
                tuple(item.get("months", range(1, 13))),
            )
        )
    result = tuple(tariffs)
    validate_tariffs(result, clock, zone)
    return result


def solar_start_headroom_kw(options) -> float:
    """Export headroom above element power for a solar start (decision D3).

    The agreed value is the constant SOLAR_START_HEADROOM_KW (0.3 kW: 3.3 kW for
    the 3 kW element). Only an installation whose stored pre-0.18 value differed
    keeps that value (migrate_0_18_0), so the upgrade cannot silently change
    solar qualification; diagnostics report which basis applies.
    """
    value = options.get("export_headroom_kw")
    return SOLAR_START_HEADROOM_KW if value is None else number(value)


def parse_options(options):
    """Validate every ACTIVE setting. Retired keys are never read or validated."""
    values = {**DEFAULT_OPTIONS, **options}
    for key in (
        "meter_verified",
        "tariff_verified",
        "import_positive",
        "forecast_enabled",
        "weekend_peak",
        "learned_planning_enabled",
        "learning_hardware_qualified",
        "optional_solar_boost",
        "controller_four_state_qualified",
        "weekend_solar_heating",
    ):
        if type(values[key]) is not bool:
            raise ValueError("settings_invalid")
    for key, (low, high) in CONTROLLER_BOUNDS.items():
        if not low <= number(values[key]) <= high:
            raise ValueError("controller_setting_out_of_range")
    for key in ("controller_command_topic", "controller_notify_service"):
        if not isinstance(values[key], str) or len(values[key]) > 64:
            raise ValueError("controller_setting_invalid")
    stamp = values["heater_meter_verification"]
    solar_stamp = values["ct_free_solar_verification"]
    if (
        not isinstance(solar_stamp, str)
        or len(solar_stamp) > 300
        or (
            solar_stamp
            and not re.fullmatch(
                r"sensor\.[a-z0-9_]+\|(W|kW)\|(import_positive|export_positive)\|[0-9]+(?:\.[0-9]+)?",
                solar_stamp,
            )
        )
    ):
        raise ValueError("controller_setting_invalid")
    from .targets import validate_roles

    validate_roles(
        *(number(values[key]) for key in ("baseline_c", "normal_storage_c", "solar_boost_c"))
    )
    if (
        not 50 <= number(values["tank_litres"]) <= 500
        or not 2 <= number(values["element_kw"]) <= 3.6
        or not 5 <= number(values["completion_margin_minutes"]) <= 120
        or not 0 <= number(values["boost_useful_fraction"]) <= 1
        or not 0 <= number(values["boost_min_saving_aud"]) <= 2
        or values["peak_heating_policy"]
        not in ("Never schedule heating during peak", "Verified solar-only heating")
    ):
        raise ValueError("dual_storage_settings_invalid")
    if not (
        0 <= number(values["optional_heat_margin_aud_per_kwh"]) <= 0.20
        and 0.10 <= number(values["pause_min_saving_aud"]) <= 2
    ):
        raise ValueError("economic_setting_out_of_range")
    if not 0 <= solar_start_headroom_kw(values) <= 3:
        raise ValueError("settings_invalid")
    if (
        not isinstance(stamp, str)
        or len(stamp) > 258
        or (stamp and not re.fullmatch(r"sensor\.[a-z0-9_]+\|(W|kW)", stamp))
    ):
        raise ValueError("heater_meter_verification_invalid")
    notify = values["controller_notify_service"].strip()
    if notify and not NOTIFY_SERVICE_PATTERN.match(notify):
        raise ValueError("notify_service_invalid")  # F4: was silently ignored
    for key, low, high in NEXT_RANGES:
        if type(values[key]) is bool or not low <= number(values[key]) <= high:
            raise ValueError("settings_invalid")
    if number(values["completion_margin_minutes"]) <= number(values["peak_command_lead_minutes"]):
        raise ValueError("completion_margin_not_after_peak_lead")
    if not 12 * 60 <= _minute(values["weekend_end_time"]) <= 23 * 60:
        raise ValueError("tariff_time_invalid")
    for key in WHOLE_NUMBER_OPTIONS:
        if number(values[key]) != int(number(values[key])):
            raise ValueError("whole_number_required")  # F10
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
    if profile not in {"flat", "aurora_93", "custom"}:
        raise ValueError("tariff_invalid")
    raw = values["tariff_periods"]
    # The stored custom weekly table is ALWAYS validated, even while the Aurora
    # profile is active. It is persisted, and switching the profile select later
    # must never activate an unvalidated table. One invalid field saves nothing.
    _periods(raw, rates, values["tariff_clock"], values["time_zone"])
    if profile == "flat":
        raw = json.dumps(
            [{"days": list(range(7)), "start": "00:00", "end": "00:00", "kind": "off_peak"}]
        )
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
    tariffs = _periods(raw, rates, values["tariff_clock"], values["time_zone"])
    if (
        not _minute(values["daytime_start"])
        < _minute(values["storage_ready_time"])
        < _minute(values["baseline_start"])
    ):
        raise ValueError("daytime_times_invalid")
    settings = Settings(
        **{
            key: values[key]
            if key
            in {
                "meter_verified",
                "tariff_verified",
                "import_positive",
                "tariff_clock",
                "time_zone",
                "forecast_enabled",
            }
            else number(values[key])
            for key in Settings.__dataclass_fields__
        }
    )
    validate_settings(settings)
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


def migrate_0_18_0(options):
    """1.5 -> 1.6: move every retired setting into the RETIRED_RECORD.

    Returns (options, moved_keys, kept_headroom_kw). Values are moved verbatim,
    never deleted; an existing record entry is never overwritten (idempotent).
    Restore/undo snapshot entries for retired keys move with them.

    Decision D3: a valid stored ``export_headroom_kw`` that differs from the
    agreed 0.3 kW stays active (top level), so solar qualification is not changed
    silently; the caller logs it and diagnostics report it.
    """
    result = dict(options)
    raw = result.get(RETIRED_RECORD)
    record = dict(raw) if isinstance(raw, dict) else {}
    kept = None
    if "export_headroom_kw" in result:
        try:
            value = number(result["export_headroom_kw"])
        except (TypeError, ValueError, OverflowError):
            value = None
        if value is not None and 0 <= value <= 3 and abs(value - SOLAR_START_HEADROOM_KW) > 1e-9:
            kept = value
    moved = []
    for key in sorted(RETIRED_OPTIONS):
        if key not in result or (key == "export_headroom_kw" and kept is not None):
            continue
        record.setdefault(key, result.pop(key))
        moved.append(key)
    backup = result.get(BACKUP_KEY)
    if isinstance(backup, dict):
        stale = {key: value for key, value in backup.items() if key not in DEFAULT_OPTIONS}
        if stale:
            record.setdefault(BACKUP_KEY, stale)
            remaining = {k: v for k, v in backup.items() if k in DEFAULT_OPTIONS}
            if remaining:
                result[BACKUP_KEY] = remaining
            else:
                result.pop(BACKUP_KEY)
    if record:
        result[RETIRED_RECORD] = record
    return result, moved, kept


def saved_options(options):
    """Merge defaults while preserving legacy custom tariff periods and overrides."""
    values = {**DEFAULT_OPTIONS, **options}
    if (
        "tariff_profile" not in options
        and values["tariff_periods"] != DEFAULT_OPTIONS["tariff_periods"]
    ):
        values["tariff_profile"] = "custom"
    return values
