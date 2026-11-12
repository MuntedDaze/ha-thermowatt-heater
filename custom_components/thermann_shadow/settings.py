"""One metadata catalogue for native controls, forms, defaults and validation."""

from dataclasses import dataclass
from types import MappingProxyType

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
        "Morning minimum (hard)",
        "Comfort",
        "Minimum reading (bottom-of-tank T_Avg) by the hard morning deadline, every day. Protected over savings when at risk. A planning threshold, NEVER a heater setpoint or hygiene temperature.",
        30,
        60,
        "°C",
    ),
    "morning_preferred_c": Setting(
        "Morning preferred reserve",
        "Comfort",
        "Preferred reading by the preferred morning time, every day: extra reserve before showers, aimed for when reasonably achievable. Once that time passes unmet, only the hard minimum is pursued. Not lower than the minimum.",
        30,
        60,
        "°C",
    ),
    "morning_preferred_time": Setting(
        "Morning ready (preferred)",
        "Comfort",
        "Hobart local, every day. Aim to reach the morning threshold by this time.",
        kind="time",
    ),
    "morning_hard_time": Setting(
        "Morning ready (hard deadline)",
        "Comfort",
        "Hobart local, every day (showers). If the preferred time is missed, heating continues for this deadline; it is never abandoned. Must not be earlier than the preferred time.",
        kind="time",
    ),
    "morning_time": Setting(
        "Legacy: weekend morning time",
        "Legacy",
        "Not used by automatic control since 0.7.0 (see the two morning ready times). Kept so saved settings are unchanged; only the legacy shadow display uses it.",
        kind="time",
    ),
    "shower_time_enabled": Setting(
        "Legacy: earlier weekday shower time",
        "Legacy",
        "Not used by automatic control since 0.7.0. Kept so saved settings are unchanged.",
        kind="switch",
    ),
    "shower_time": Setting(
        "Legacy: weekday shower-ready time",
        "Legacy",
        "Not used by automatic control since 0.7.0. Kept so saved settings are unchanged.",
        kind="time",
    ),
    "expected_morning_draw_c": Setting(
        "Expected morning hot-water use",
        "Comfort",
        "Reading drop assumed for morning showers when planning the afternoon target. An assumption (about 11 °C was seen on 11 Nov), not a measurement.",
        0,
        40,
        "°C",
    ),
    "standing_loss_c_per_hour": Setting(
        "Assumed standing heat loss",
        "Advanced",
        "Reading drop per hour with no use or heating. Not yet measured for this tank.",
        0,
        2,
        "°C/h",
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
        "Weekend (no-peak) afternoon ready time, Hobart local, after noon. Weekdays use the evening peak start automatically: 16:00 standard time, 17:00 daylight time.",
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
        "FUTURE CONTROL ONLY: minimum benefit per heater switch. The 0.4.0 advisor uses the per-kWh waiting threshold instead.",
        0,
        5,
        "AUD",
    ),
    "wait_benefit_aud_per_kwh": Setting(
        "Minimum saving to recommend waiting",
        "Heating Cycles",
        "Waiting is only recommended if it saves at least this much per kWh that would otherwise be heated now (first minimum cycle; 0.05 = 7.5 c for 30 min) and the comfort fallback stays viable. Solar later vs off-peak grid now is 7.7 c/kWh.",
        0,
        0.5,
        "AUD/kWh",
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
    "pv_ac_limit_kw": Setting(
        "Inverter AC output limit",
        "Solar & Forecasting",
        "Combined AC limit of the single GoodWe inverter for BOTH arrays; forecasts above it are clipped.",
        1,
        30,
        "kW",
    ),
    "base_load_source": Setting(
        "Household load basis",
        "Solar & Forecasting",
        "measured_only: de-embedded measured base load (heater removed). measured_then_published also uses the published load forecast after 2 h; today's EMHASS load includes heater cycles.",
        choices=("measured_only", "measured_then_published"),
        kind="select",
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
    "controller_command_topic": Setting(
        "Controller command topic",
        "Controller",
        "Commissioning: the Thermowatt MQTT mode command topic for your heater, exactly as written in the commissioning runbook (Stage B). Blank = the controller can never command.",
        kind="text",
    ),
    "controller_bridge_qualified": Setting(
        "Bridge commands qualified (T3)",
        "Controller",
        "Commissioning Stage B: ON only after the supervised T3 test showed the bridge's Manual:70 (from OFF) and off (from Manual 70) reproduce the app results. Requires Thermowatt add-on 1.3.9 or later.",
        kind="switch",
    ),
    "controller_min_heating_minutes": Setting(
        "Minimum heating period",
        "Controller",
        "Shortest time Manual (heating permitted) is kept before parking, unless the thermostat has already stopped the element.",
        30,
        180,
        "min",
    ),
    "controller_min_rest_minutes": Setting(
        "Minimum rest period",
        "Controller",
        "Shortest time parked before heating is permitted again.",
        30,
        240,
        "min",
    ),
    "controller_max_commands_per_day": Setting(
        "Maximum commands per day",
        "Controller",
        "Rolling 24 h limit on mode commands. A typical day needs 2 (one heating period) or 4 (morning and afternoon). The last 2 are reserved for a comfort start and its park.",
        4,
        10,
    ),
    "controller_confirmation_timeout_minutes": Setting(
        "Command confirmation timeout",
        "Controller",
        "If no status confirms a command within this time, automatic control locks until you acknowledge. At least one poll interval plus margin.",
        35,
        120,
        "min",
    ),
    "controller_max_requests_per_day": Setting(
        "Cloud request budget per day",
        "Controller",
        "No command is sent once the bridge's local request count over 24 h reaches this. Normal 30-minute polling uses about 150/day.",
        160,
        400,
    ),
    "controller_execution_latency_minutes": Setting(
        "Execution latency reserve",
        "Controller",
        "Comfort deadlines are planned this much earlier, and the pre-peak park is brought forward by it. With bridge 1.3.10 a command normally reaches the heater within about a minute; the 30-minute default is a conservative margin you may reduce after the supervised trial.",
        0,
        60,
        "min",
    ),
    "controller_notify_service": Setting(
        "Notification service",
        "Controller",
        "Optional notify service name, e.g. mobile_app_phone (without notify.). Blank = Home Assistant notifications only.",
        kind="text",
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

# Truthful "original" defaults: the value each setting first shipped with
# (0.2.0 for shared keys, 0.3.0 for new keys; identical today). RECOMMENDED is
# DEFAULT_OPTIONS. A future release that changes a recommendation must change
# DEFAULT_OPTIONS only and keep this mapping, so the dashboard stays honest.
ORIGINAL_DEFAULTS = MappingProxyType(
    {
        **DEFAULT_OPTIONS,
        # Recommendations changed in 0.4.0 by owner requirement; what shipped first:
        "morning_threshold_c": 40.0,
        "morning_time": "07:00",
    }
)

# Owner facts, verifications, contract data and references are never
# "preferences": restoring recommendations must not rewrite them.
PRESERVE_ON_RESTORE = frozenset(
    {
        "paused",
        "meter_verified",
        "tariff_verified",
        "import_positive",
        "expected_native_target_c",
        "native_schedule_periods",
        "native_schedule_clock",
        "native_schedule_clock_verified",
        "native_clock_check_date",
        "t_comfort_reference_c",
        # Tariff contract: a verified contract is not reset to the Aurora 93
        # defaults merely because comfort/cycle preferences are restored.
        "tariff_clock",
        "tariff_profile",
        "tariff_periods",
        "weekend_peak",
        "off_peak_rate",
        "shoulder_rate",
        "peak_rate",
        "feed_in_rate",
        "peak_morning_start",
        "peak_morning_end",
        "peak_evening_start",
        "peak_evening_end",
        # Commissioning facts are never "preferences".
        "controller_command_topic",
        "controller_bridge_qualified",
        "controller_notify_service",
        # 0.7.1: command safety timing, budgets and data-freshness limits are
        # system settings, not preferences; a restore never changes them.
        "controller_min_heating_minutes",
        "controller_min_rest_minutes",
        "controller_max_commands_per_day",
        "controller_confirmation_timeout_minutes",
        "controller_max_requests_per_day",
        "controller_execution_latency_minutes",
        "status_max_age_minutes",
        "grid_max_age_seconds",
    }
)
# 0.7.1: settings that change WHERE commands go, WHETHER they may be sent, HOW
# often, or what a measurement or a price MEANS. Changing one while automatic
# control is on could silently bypass a commissioning gate, redirect commands,
# invert the meter or reprice decisions mid-run, so it is accepted only while
# automatic control is OFF. ("sources" is the sensor-mapping page of Configure.)
LOCKED_WHILE_ACTIVE = frozenset(
    {
        "controller_command_topic",
        "controller_bridge_qualified",
        "controller_min_heating_minutes",
        "controller_min_rest_minutes",
        "controller_max_commands_per_day",
        "controller_confirmation_timeout_minutes",
        "controller_max_requests_per_day",
        "controller_execution_latency_minutes",
        "meter_verified",
        "import_positive",
        "tariff_verified",
        "tariff_profile",
        "tariff_clock",
        "tariff_periods",
        "weekend_peak",
        "off_peak_rate",
        "shoulder_rate",
        "peak_rate",
        "feed_in_rate",
        "peak_morning_start",
        "peak_morning_end",
        "peak_evening_start",
        "peak_evening_end",
        "status_max_age_minutes",
        "grid_max_age_seconds",
        "sources",
    }
)
RESTORED = tuple(key for key in DEFAULT_OPTIONS if key not in PRESERVE_ON_RESTORE)
assert not set(RESTORED) & LOCKED_WHILE_ACTIVE  # restore/undo never need control off


def _same(a, b) -> bool:
    if a == b:
        return True
    try:
        return isinstance(a, (int, float)) and isinstance(b, (int, float)) and float(a) == float(b)
    except (TypeError, ValueError):
        return False


def locked_changes(before: dict, after: dict) -> list[str]:
    """Locked keys whose value differs between two complete option sets."""
    from .config import DEFAULT_OPTIONS

    changed = []
    for key in sorted(LOCKED_WHILE_ACTIVE):
        default = DEFAULT_OPTIONS.get(key)
        old, new = before.get(key, default), after.get(key, default)
        if key == "sources":
            old, new = dict(old or {}), dict(new or {})
        if not _same(old, new):
            changed.append(key)
    return changed


def locked_message(keys) -> str:
    names = [CATALOG[key].name if key in CATALOG else "Sensor mappings" for key in keys]
    return (
        "Turn off Automatic heater control before changing: "
        + ", ".join(names)
        + ". These settings decide where commands go, whether they may be sent or what "
        "a measurement or price means. Nothing was saved."
    )


BACKUP_KEY = "restore_backup"


def recommended_options(current):
    """Only preferences; never rewrite mappings, verification, tariff or references.

    The replaced values are kept under BACKUP_KEY so one restore can be undone.
    """
    backup = {key: current[key] for key in RESTORED if current.get(key) != DEFAULT_OPTIONS[key]}
    restored = {**current, **{key: DEFAULT_OPTIONS[key] for key in RESTORED}}
    restored.pop(BACKUP_KEY, None)  # never let Undo revert to an older restore
    if backup:
        restored[BACKUP_KEY] = backup
    return restored


def undo_restore(current):
    """Re-apply the preferences replaced by the last restore, then forget them."""
    backup = current.get(BACKUP_KEY)
    if not isinstance(backup, dict) or not backup or not set(backup) <= set(RESTORED):
        raise ValueError("no_restore_to_undo")
    result = {key: value for key, value in current.items() if key != BACKUP_KEY}
    return {**result, **backup}


def apply_changes(values, changes):
    """Ordinary edits. After a restore, an edited key leaves the undo snapshot:
    it is the owner's newest decision and must not be reverted by Undo."""
    result = {**values, **changes}
    backup = result.get(BACKUP_KEY)
    if isinstance(backup, dict):
        backup = {
            key: value
            for key, value in backup.items()
            if key not in changes or changes[key] == values.get(key)
        }
        if backup:
            result[BACKUP_KEY] = backup
        else:
            result.pop(BACKUP_KEY)
    return result


def describe(key, current):
    """CURRENT, RECOMMENDED and ORIGINAL values; identical defaults are combined."""
    recommended, original = DEFAULT_OPTIONS[key], ORIGINAL_DEFAULTS[key]
    return {
        "current_value": current,
        "recommended_default": recommended,
        "original_default": original,
        "recommended_equals_original": recommended == original,
        "changed_from_recommended": current != recommended,
        "restore_recommended": "restores" if key in RESTORED else "preserves",
    }
