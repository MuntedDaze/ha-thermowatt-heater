"""One metadata catalogue for native controls, forms, defaults and validation."""

from dataclasses import dataclass
from zoneinfo import available_timezones
from types import MappingProxyType

from .config import BACKUP_KEY, DEFAULT_OPTIONS


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
    "forecast_enabled": Setting(
        "Use published forecasts",
        "Advanced",
        "The EMHASS PV AND household-load forecasts with generation timestamps. Optional for basic no-solar tariff control. Settings cannot change while automatic control is on. If the forecast is missing, weekday grid heating waits for the latest start instead of starting at once, and an alert is raised after an hour.",
        kind="switch",
    ),
    "forecast_uncertainty": Setting(
        "Forecast uncertainty margin",
        "Advanced",
        "Fraction: reduce PV and increase household load. 0.25 means 25%; never guaranteed surplus.",
        0,
        0.9,
    ),
    "forecast_house_margin_kw": Setting(
        "Extra forecast household load",
        "Advanced",
        "Additional allowance for competing appliances, beyond forecast demand.",
        0,
        5,
        "kW",
    ),
    "meter_verified": Setting(
        "Meter sign and units verified",
        "System",
        "Owner verification, not an optimisation preference. Restore recommendations preserves this flag.",
        kind="switch",
    ),
    "tariff_verified": Setting(
        "Tariff contract verified",
        "System",
        "Owner confirmation of rates, periods and clock. Restore preserves this flag.",
        kind="switch",
    ),
    "import_positive": Setting(
        "Positive grid means import",
        "System",
        "OFF means export-positive. Verify the actual meter with a known load; restore preserves direction.",
        kind="switch",
    ),
    "tariff_clock": Setting(
        "Tariff clock",
        "Advanced",
        "Use your verified contract: standard is fixed AEST UTC+10; local is Australia/Hobart with DST. Other time zones are not qualified.",
        choices=("standard", "local"),
        kind="select",
    ),
    "tariff_profile": Setting(
        "Tariff periods mode",
        "Advanced",
        "aurora_93 uses editable weekday peak times below; custom retains advanced weekly JSON periods in Configure.",
        choices=("flat", "aurora_93", "custom"),
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
        "AUD/kWh from your contract (0-2).",
        0,
        2,
        "AUD/kWh",
    ),
    "peak_rate": Setting(
        "Peak import price",
        "Advanced",
        "AUD/kWh from your contract (0-2).",
        0,
        2,
        "AUD/kWh",
    ),
    "shoulder_rate": Setting(
        "Shoulder import price",
        "Advanced",
        "AUD/kWh (0-2). Used only by custom weekly periods with shoulder entries.",
        0,
        2,
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
        "Advanced",
        "Combined AC limit of the single GoodWe inverter for BOTH arrays; forecasts above it are clipped.",
        1,
        30,
        "kW",
    ),
    "forecast_max_age_minutes": Setting(
        "Maximum forecast generation age",
        "Advanced",
        "Older forecasts are ignored (no future solar is assumed). EMHASS publishes every 30 minutes, so at least 35. Republishing an old forecast does not freshen it.",
        35,
        360,
        "min",
    ),
    "status_max_age_minutes": Setting(
        "Maximum cloud poll age",
        "System",
        "Planner freshness gate for the heater status. Must exceed the bridge's 30-minute polling; does not change polling or request a refresh.",
        35,
        90,
        "min",
    ),
    "grid_max_age_seconds": Setting(
        "Maximum power reading age",
        "System",
        "Missing/stale observations reset economic holds; no cloud calls.",
        30,
        300,
        "s",
    ),
    "tariff_periods": Setting(
        "Custom weekly tariff periods",
        "Advanced",
        "Configure advanced JSON: days 0–6, start/end HH:MM, kind. Used only with custom tariff mode; no YAML editing.",
        kind="form",
    ),
    "controller_command_topic": Setting(
        "Controller command topic",
        "System",
        "Commissioning: the Thermowatt MQTT mode command topic for your heater, exactly as written in the commissioning runbook (Stage B). Blank = the controller can never command.",
        kind="text",
    ),
    "controller_max_commands_per_day": Setting(
        "Maximum commands per day",
        "System",
        "Rolling 24 h limit for OPTIONAL solar starts: none is sent once this many commands have gone out. Essential commands (normal storage, baseline maintenance and the 12hr Override 62°C) may go 6 beyond it, so optional solar activity cannot consume their reserved capacity; that higher cap still stops a fault that loops. A switch to OFF is never held back. A typical weekday needs about 4 commands.",
        4,
        10,
    ),
    "controller_confirmation_timeout_minutes": Setting(
        "Command confirmation timeout",
        "System",
        "If no status confirms a command within this time, automatic control locks until you acknowledge. At least one poll interval plus margin.",
        35,
        120,
        "min",
    ),
    "controller_max_requests_per_day": Setting(
        "Cloud request budget per day",
        "System",
        "No command is sent once the bridge's local request count over 24 h reaches this. Normal 30-minute polling uses about 150/day.",
        160,
        400,
    ),
    "controller_notify_service": Setting(
        "Notification service",
        "System",
        "Optional phone notifications for faults, unconfirmed commands and comfort risks: the notify service name only, for example mobile_app_phone (no 'notify.' in front). Blank = Home Assistant notifications only.",
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
CATALOG["heater_meter_verification"] = Setting(
    "Commissioned hot-water power entity and unit",
    "System",
    "After an electrician verifies the exclusive hot-water circuit, sign, units, reporting cadence, "
    "OFF/ON and outage tests, enter entity_id|W or entity_id|kW. Empty disables optional heating. "
    "Remapping the power sensor clears this record; no relay control is used.",
    kind="text",
)
CATALOG.update({})
CATALOG.update(
    {
        "optional_heat_margin_aud_per_kwh": Setting(
            "Optional heat minimum saving",
            "Advanced",
            "Minimum prospective saving against off-peak grid, including lost feed-in value. "
            "Does not relax measured-power or import guards.",
            0,
            0.20,
            "AUD/kWh",
        ),
        "pause_min_saving_aud": Setting(
            "Minimum saving to pause weekday heat",
            "Advanced",
            "A later window must save this much and still fit before the soft target.",
            0.10,
            2,
            "AUD",
        ),
    }
)
CATALOG.update(
    {
        "baseline_c": Setting(
            "Overnight baseline temperature",
            "Everyday",
            "Supported native thermostat target during permitted nights/weekends; does not prove achieved whole-tank temperature or independently establish compliance. Follow appliance/plumbing requirements; native protective behaviour is not verified by this software.",
            unit="°C",
            kind="select",
            choices=("45", "62"),
        ),
        "normal_storage_c": Setting(
            "Normal weekday storage temperature",
            "Everyday",
            "Required weekday thermostat target. Only bridge-supported values; 62 is the economical default.",
            unit="°C",
            kind="select",
            choices=("62", "70"),
        ),
        "solar_boost_c": Setting(
            "Optional solar storage temperature",
            "Everyday",
            "Upper optional target, at least the normal target. Equal targets avoid a separate top-up.",
            unit="°C",
            kind="select",
            choices=("62", "70"),
        ),
        "optional_solar_boost": Setting(
            "Enable optional solar boost",
            "Everyday",
            "Allow extra storage with either a commissioned dedicated hot-water circuit meter (CT) or the separately configured experimental CT-free GoodWe grid-meter setup. Turning this switch on alone does not start boosting: automatic control must be enabled, and measurement, solar surplus, cost, peak-policy and safety checks must all pass. Required storage still works without a CT; the separate 12-hour Override is unchanged.",
            kind="switch",
        ),
        "peak_heating_policy": Setting(
            "Heating during peak periods",
            "Everyday",
            "The Never option takes priority over routine solar opportunities. Solar-only requires fresh verified grid measurements, qualified circuit or CT-free operation and all command safeguards. Explicit owner override/native protections remain independent.",
            kind="select",
            choices=("Never schedule heating during peak", "Verified solar-only heating"),
        ),
        "tank_litres": Setting(
            "Tank capacity",
            "Advanced",
            "Nominal tank volume for conservative energy/time estimates, not measured hot-water availability.",
            50,
            500,
            "L",
        ),
        "element_kw": Setting(
            "Nominal element power",
            "Advanced",
            "Supported resistive-element planning reference. CT-free operation never treats this as verified draw.",
            2,
            3.6,
            "kW",
        ),
        "completion_margin_minutes": Setting(
            "Preferred completion before peak",
            "Everyday",
            "Soft planning margin; required heating may continue until the hard peak boundary.",
            5,
            120,
            "min",
        ),
        "boost_useful_fraction": Setting(
            "Expected useful fraction of extra solar heat",
            "Advanced",
            "Planning assumption 0–1 for extra heat used before the next cheap opportunity. Includes a bounded standby-loss allowance. Zero prevents optional boosts; not learned evidence.",
            0,
            1,
        ),
        "controller_four_state_qualified": Setting(
            "Four-state commands qualified (1.3.14)",
            "System",
            "Only after separately authorised supervised qualification of OFF/45/62/70 transitions. Does not authorise live operation by itself.",
            kind="switch",
        ),
    }
)
CATALOG["learned_planning_enabled"] = Setting(
    "Use validated conservative learned heating rate",
    "System",
    "Disabled until real independent samples, held-out accuracy and hardware qualification pass. A learned lower bound may advance required heating, never delay it beyond nominal/live-watt planning.",
    kind="switch",
)
CATALOG["learning_hardware_qualified"] = Setting(
    "Heating learning independently qualified",
    "System",
    "Owner commissioning gate, never set from synthetic tests. Remapping the meter, changing its unit or nominal tank/power clears this flag.",
    kind="switch",
)


CATALOG["time_zone"] = Setting(
    "Household time zone",
    "Advanced",
    "IANA zone; a new installation starts from Home Assistant's configured zone. Tariff local/fixed standard basis is separate. Changing this requires control disabled.",
    choices=tuple(sorted(available_timezones())),
    kind="select",
)
for key, name in (
    ("daytime_start", "Weekday storage window starts"),
    ("storage_ready_time", "Weekday storage ready time without peak"),
    ("baseline_start", "Return to overnight baseline without peak"),
):
    CATALOG[key] = Setting(
        name,
        "Everyday",
        "Household local clock. Used for required weekday storage when the electricity plan has no peak deadline. Start < ready < baseline return. Not an electrical peak or a hygiene guarantee.",
        kind="time",
    )

_DUAL_PROTECTED = frozenset(
    {
        "baseline_c",
        "normal_storage_c",
        "solar_boost_c",
        "tank_litres",
        "element_kw",
        "completion_margin_minutes",
        "optional_solar_boost",
        "peak_heating_policy",
        "boost_useful_fraction",
        "controller_four_state_qualified",
    }
)
CATALOG["boost_min_saving_aud"] = Setting(
    "Minimum benefit of optional solar boost",
    "Advanced",
    "Expected net dollars saved must exceed this per boost as well as the existing per-kWh margin; avoids extra commands for trivial benefit.",
    0,
    2,
    "AUD",
)
_DUAL_PROTECTED = _DUAL_PROTECTED | {"boost_min_saving_aud"}
CATALOG["ct_free_solar_verification"] = Setting(
    "CT-free solar commissioning record",
    "System",
    "Leave blank until supervised grid-sign, continuity, command and protective OFF tests pass. "
    "Exact grid_entity|W_or_kW|import_positive_or_export_positive|nominal_kW record. "
    "Does not prove element operation. A mapped circuit meter must remain valid instead.",
    kind="text",
)
_DUAL_PROTECTED = _DUAL_PROTECTED | {"ct_free_solar_verification"}

CATALOG["weekend_solar_heating"] = Setting(
    "Weekend solar-led normal storage",
    "Advanced",
    "Use measured PV to open a weekend comfort window. 62 normal storage is planned to the storage-ready time with off-peak grid assistance allowed; it is not solar-only heating.",
    0,
    1,
    None,
    kind="switch",
)
CATALOG["weekend_pv_start_kw"] = Setting(
    "Weekend daylight trigger",
    "Advanced",
    "Measured PV production in kW. The first fresh report at or above this opens the weekend window until the end time; 0.5 kW means 500 W.",
    0.1,
    3.6,
    "kW",
    kind="number",
)
CATALOG["weekend_end_time"] = Setting(
    "Weekend latest return to baseline",
    "Advanced",
    "Household local clock: the weekend window ends and the thermostat target returns to baseline at this time. This does not cool stored water.",
    0,
    1,
    None,
    kind="time",
)
CATALOG["solar_cooldown_minutes"] = Setting(
    "Wait after confirmed solar withdrawal",
    "Advanced",
    "Minutes after confirmed withdrawal OFF before another optional solar start. Fresh qualification can overlap this wait. Ordinary 15-minute command spacing also applies.",
    10,
    60,
    "min",
    kind="number",
)
CATALOG["pre_peak_observation_minutes"] = Setting(
    "Check hot water before peak",
    "Advanced",
    "Minutes before each configured peak to arrange a fresh status observation; before the evening peak it is also when the low-water warning is assessed. Tariff-clock/DST conversion is automatic.",
    5,
    60,
    "min",
    kind="number",
)
CATALOG["peak_command_lead_minutes"] = Setting(
    "Request peak OFF this much early",
    "Advanced",
    "Minutes reserved for local evaluation, cloud command and confirmation before peak. This is not a guaranteed electrical cutoff.",
    1,
    10,
    "min",
    kind="number",
)
CATALOG["low_water_warning_c"] = Setting(
    "Low bottom-temperature warning",
    "Advanced",
    "Notify only on a fresh bottom-probe reading below this temperature shortly before the evening peak (never before the morning peak). A notification only: not a thermostat target, whole-tank measurement, heating permission or automatic emergency.",
    20,
    45,
    "°C",
    kind="number",
)
_DUAL_PROTECTED = _DUAL_PROTECTED | {
    "low_water_warning_c",
    "pre_peak_observation_minutes",
    "weekend_solar_heating",
    "peak_command_lead_minutes",
    "weekend_pv_start_kw",
    "solar_cooldown_minutes",
    "weekend_end_time",
}
assert set(CATALOG) == set(DEFAULT_OPTIONS)
# Interface groups. Everyday: what a homeowner adjusts. Advanced: tariff,
# forecasts, economic and model assumptions. System: commissioning, safety
# timing, budgets and verification (most need automatic control OFF to edit).
# Retired settings are not in the catalogue at all (config.RETIRED_OPTIONS).
GROUPS = ("Everyday", "Advanced", "System")
assert {meta.group for meta in CATALOG.values()} <= set(GROUPS)

# Truthful "original" defaults: the value each setting first shipped with
# (0.2.0 for shared keys, 0.3.0 for new keys; identical today). RECOMMENDED is
# DEFAULT_OPTIONS. A future release that changes a recommendation must change
# DEFAULT_OPTIONS only and keep this mapping, so the dashboard stays honest.
ORIGINAL_DEFAULTS = MappingProxyType(
    {
        **DEFAULT_OPTIONS,
        # Recommendations changed in 0.4.0 by owner requirement; what shipped first:
        "meter_verified": True,
        "tariff_verified": True,
        "import_positive": False,
        "tariff_clock": "standard",
    }
)

# Owner facts, verifications, contract data, commissioning, safety limits and
# household choices are never "preferences": restoring recommendations must not
# rewrite them.
PRESERVE_ON_RESTORE = (
    frozenset(
        {
            "meter_verified",
            "tariff_verified",
            "import_positive",
            # Tariff contract: a verified contract is not reset to the Aurora 93
            # defaults merely because preferences are restored.
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
            # Commissioning facts, budgets and data-freshness limits.
            "controller_command_topic",
            "controller_notify_service",
            "controller_max_commands_per_day",
            "controller_confirmation_timeout_minutes",
            "controller_max_requests_per_day",
            "status_max_age_minutes",
            "grid_max_age_seconds",
            # 0.9.1 (audit M4): whether EMHASS is used at all is commissioning.
            "forecast_enabled",
            "heater_meter_verification",
            "optional_heat_margin_aud_per_kwh",
            "pause_min_saving_aud",
            "learned_planning_enabled",
            "learning_hardware_qualified",
            "time_zone",
            "daytime_start",
            "storage_ready_time",
            "baseline_start",
        }
    )
    | _DUAL_PROTECTED
)

# 0.17.1: preferences that never choose a command, a target, a meter meaning or
# a price may be edited while automatic control is on. Each takes effect at the
# next evaluation through the same validation. They stay preserved on Restore.
SAFE_WHILE_ACTIVE = frozenset(
    {
        "low_water_warning_c",  # a warning threshold only
        "pre_peak_observation_minutes",  # when a status read is arranged; no authority
    }
)

# 0.7.1: settings that change WHERE commands go, WHETHER they may be sent, HOW
# often, or what a measurement or a price MEANS. Changing one while automatic
# control is on could silently bypass a commissioning gate, redirect commands,
# invert the meter or reprice decisions mid-run, so it is accepted only while
# automatic control is OFF. ("sources" is the sensor-mapping page of Configure.)
LOCKED_WHILE_ACTIVE = (
    frozenset(
        {
            "controller_command_topic",
            "controller_max_commands_per_day",
            "controller_confirmation_timeout_minutes",
            "controller_max_requests_per_day",
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
            "forecast_enabled",
            "sources",
            "optional_heat_margin_aud_per_kwh",
            "pause_min_saving_aud",
            "heater_meter_verification",
            "learned_planning_enabled",
            "learning_hardware_qualified",
            "time_zone",
            "daytime_start",
            "storage_ready_time",
            "baseline_start",
        }
    )
    | _DUAL_PROTECTED
) - SAFE_WHILE_ACTIVE
assert SAFE_WHILE_ACTIVE <= PRESERVE_ON_RESTORE
RESTORED = tuple(key for key in DEFAULT_OPTIONS if key not in PRESERVE_ON_RESTORE)
assert not set(RESTORED) & LOCKED_WHILE_ACTIVE


def _same(a, b) -> bool:
    if a == b:
        return True
    try:
        return isinstance(a, (int, float)) and isinstance(b, (int, float)) and float(a) == float(b)
    except (TypeError, ValueError):
        return False


def locked_changes(before: dict, after: dict) -> list[str]:
    """Locked keys whose value differs between two complete option sets."""
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
    if any(
        key in changes and changes[key] != values.get(key)
        for key in ("tank_litres", "element_kw", "heater_meter_verification")
    ):
        result["learning_hardware_qualified"] = False
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
