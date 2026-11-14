"""One metadata catalogue for native controls, forms, defaults and validation."""

from dataclasses import dataclass
from zoneinfo import available_timezones
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
        "Retired",
        "Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Minimum reading (bottom-of-tank T_Avg) by the hard morning deadline, every day. Protected over savings when at risk. A planning threshold, NEVER a heater setpoint or hygiene temperature.",
        30,
        60,
        "°C",
    ),
    "morning_preferred_c": Setting(
        "Morning preferred reserve",
        "Retired",
        "Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Preferred reading by the preferred morning time, every day: extra reserve before showers, aimed for when reasonably achievable. Once that time passes unmet, only the hard minimum is pursued. Not lower than the minimum.",
        30,
        60,
        "°C",
    ),
    "morning_preferred_time": Setting(
        "Morning ready (preferred)",
        "Retired",
        "Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Hobart local, every day. Aim to reach the morning threshold by this time.",
        kind="time",
    ),
    "morning_hard_time": Setting(
        "Morning ready (hard deadline)",
        "Retired",
        "Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Hobart local, every day (showers). If the preferred time is missed, heating continues for this deadline; it is never abandoned. Must not be earlier than the preferred time.",
        kind="time",
    ),
    "morning_time": Setting(
        "Legacy: weekend morning time",
        "Retired",
        "Not used by automatic control since 0.7.0 (see the two morning ready times). Kept so saved settings are unchanged; only the legacy shadow display uses it.",
        kind="time",
    ),
    "shower_time_enabled": Setting(
        "Legacy: earlier weekday shower time",
        "Retired",
        "Not used by automatic control since 0.7.0. Kept so saved settings are unchanged.",
        kind="switch",
    ),
    "shower_time": Setting(
        "Legacy: weekday shower-ready time",
        "Retired",
        "Not used by automatic control since 0.7.0. Kept so saved settings are unchanged.",
        kind="time",
    ),
    "expected_morning_draw_c": Setting(
        "Expected morning hot-water use",
        "Retired",
        "Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Reading drop assumed for morning showers when planning the afternoon target. An assumption (about 11 °C was seen on 11 Nov), not a measurement.",
        0,
        40,
        "°C",
    ),
    "standing_loss_c_per_hour": Setting(
        "Assumed standing heat loss",
        "Retired",
        "Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Reading drop per hour with no use or heating. Not yet measured for this tank.",
        0,
        2,
        "°C/h",
    ),
    "target_c": Setting(
        "Afternoon storage target",
        "Retired",
        "Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Selected model target is never silently reduced. 65–70°C is a planning range, not a newly qualified command limit.",
        65,
        70,
        "°C",
    ),
    "evening_time": Setting(
        "Weekend afternoon ready time",
        "Retired",
        "Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Weekend (no-peak) afternoon ready time, Hobart local, after noon. Weekdays use the evening peak start automatically: 16:00 standard time, 17:00 daylight time.",
        kind="time",
    ),
    "margin_minutes": Setting(
        "Heating time allowance",
        "Retired",
        "Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Extra full-power model minutes when heat is required. Uncalibrated; comfort overrides optional dwell.",
        0,
        120,
        "min",
    ),
    "min_solar_kw": Setting(
        "Minimum useful net surplus",
        "Retired",
        "Partial solar can be worthwhile. Economic comparison must also pass; never a variable-power command.",
        0,
        3,
        "kW",
    ),
    "export_headroom_kw": Setting(
        "Solar headroom",
        "Retired",
        "Deduct from measured surplus for uncertain household loads.",
        0,
        3,
        "kW",
    ),
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
    "solar_hold_minutes": Setting(
        "Solar start qualification",
        "Retired",
        "Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. How long the planner's choice between optional economic options (heat now, wait, no difference) must persist before it changes, so a passing cloud does not flip the plan. Comfort, data gates and peak decisions are never delayed by it.",
        5,
        30,
        "min",
    ),
    "solar_loss_minutes": Setting(
        "Economic loss grace period",
        "Retired",
        "Sustained cost disadvantage before a SIMULATED optional stop; short clouds do not stop a cycle.",
        0,
        120,
        "min",
    ),
    "minimum_cycle_minutes": Setting(
        "Minimum optional cycle",
        "Retired",
        "Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Shortest heating block the planner schedules. The controller's own minimum heating and rest periods still apply on top.",
        0,
        180,
        "min",
    ),
    "minimum_gap_minutes": Setting(
        "Minimum optional cycle gap",
        "Retired",
        "Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Shortest gap the planner leaves between two scheduled heating blocks (it merges closer blocks).",
        0,
        180,
        "min",
    ),
    "switching_benefit_aud": Setting(
        "Minimum economic switching benefit",
        "Retired",
        "FUTURE CONTROL ONLY: minimum benefit per heater switch. The 0.4.0 advisor uses the per-kWh waiting threshold instead.",
        0,
        5,
        "AUD",
    ),
    "wait_benefit_aud_per_kwh": Setting(
        "Minimum saving to recommend waiting",
        "Retired",
        "Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Waiting is only recommended if it saves at least this much per kWh that would otherwise be heated now (first minimum cycle; 0.05 = 7.5 c for 30 min) and the comfort fallback stays viable. Solar later vs off-peak grid now is 7.7 c/kWh.",
        0,
        0.5,
        "AUD/kWh",
    ),
    "paused": Setting(
        "Pause shadow planning",
        "Retired",
        "Pauses only hypothetical decisions; native Schedule continues.",
        kind="switch",
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
    "base_load_source": Setting(
        "Household load basis",
        "Retired",
        "Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. measured_only: de-embedded measured base load (heater removed). measured_then_published also uses the published load forecast after 2 h; today's EMHASS load includes heater cycles.",
        choices=("measured_only", "measured_then_published"),
        kind="select",
    ),
    "forecast_max_age_minutes": Setting(
        "Maximum forecast generation age",
        "Advanced",
        "Older forecasts are ignored (no future solar is assumed). EMHASS publishes every 30 minutes, so at least 35. Republishing an old forecast does not freshen it.",
        35,
        360,
        "min",
    ),
    "solar_window_minutes": Setting(
        "Recent-export scenario horizon",
        "Retired",
        "Bounded assumption for current export, never a daily forecast or guaranteed solar.",
        5,
        30,
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
    "expected_native_target_c": Setting(
        "Expected native target",
        "Retired",
        "Reference only. Different observed mode/target latches intervention; never sets the heater.",
        20,
        75,
        "°C",
    ),
    "native_schedule_clock": Setting(
        "Native schedule clock reference",
        "Retired",
        "Reference only; never adjusts the device clock or native Schedule.",
        choices=("local", "standard"),
        kind="select",
    ),
    "native_schedule_clock_verified": Setting(
        "Native clock checked",
        "Retired",
        "Owner observation only; restore preserves this verification.",
        kind="switch",
    ),
    "t_comfort_reference_c": Setting(
        "T-Comfort reference",
        "Retired",
        "Reference only; 10°C is not a useful comfort reserve. Never changes T-Comfort.",
        10,
        75,
        "°C",
    ),
    "native_clock_check_date": Setting(
        "Native clock check date",
        "Retired",
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
        "Retired",
        "Reported approximate times in JSON, for comparison only; NEVER changes the heater programme.",
        kind="form",
    ),
    "controller_command_topic": Setting(
        "Controller command topic",
        "System",
        "Commissioning: the Thermowatt MQTT mode command topic for your heater, exactly as written in the commissioning runbook (Stage B). Blank = the controller can never command.",
        kind="text",
    ),
    "controller_bridge_qualified": Setting(
        "Bridge commands qualified (T3)",
        "Retired",
        "Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Commissioning Stage B: ON only after the supervised T3 test showed the bridge's Manual:70 (from OFF) and off (from Manual 70) reproduce the app results. Requires Thermowatt add-on 1.3.9 or later.",
        kind="switch",
    ),
    "controller_three_state_qualified": Setting(
        "Three-state commands qualified (1.3.13)",
        "System",
        "Commissioning: ON only after the supervised qualification of Thermann Hot Water 1.3.13 showed every transition between OFF, Manual 45 °C and Manual 70 °C reproduces the app result, and an owner change is refused (COMMISSIONING_SIMPLIFIED.md). Automatic control cannot be enabled until it is ON.",
        kind="switch",
    ),
    "controller_min_heating_minutes": Setting(
        "Minimum heating period",
        "Retired",
        "Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Shortest time Manual (heating permitted) is kept before parking, unless the thermostat has already stopped the element.",
        30,
        180,
        "min",
    ),
    "controller_min_rest_minutes": Setting(
        "Minimum rest period",
        "Retired",
        "Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Shortest time parked before heating is permitted again, comfort starts included. At most the execution latency reserve plus 30 minutes, so a comfort start is never delayed beyond what the planner reserves.",
        30,
        90,
        "min",
    ),
    "controller_max_commands_per_day": Setting(
        "Maximum commands per day",
        "System",
        "Rolling 24 h limit for OPTIONAL solar starts (a peak-solar start, a weekend solar start): none is sent once this many commands have gone out. Essential commands (the weekday 70 °C heat, Manual 45 °C, the 12hr Override) may go 6 beyond it, so optional solar activity can never block them; that higher cap still stops a fault that loops. A switch to OFF is never held back. A typical weekday needs 4 commands in all.",
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
    "controller_execution_latency_minutes": Setting(
        "Execution latency reserve",
        "Retired",
        "Not used since 0.9.0 (the simplified policy has fixed, agreed values). Kept so saved settings and a rollback are unchanged. Comfort deadlines are planned this much earlier, and the pre-peak park is brought forward by it. With bridge 1.3.10 a command normally reaches the heater within about a minute; the 30-minute default is a conservative margin you may reduce after the supervised trial.",
        0,
        60,
        "min",
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
CATALOG.update(
    {
        "adaptive_polling_shadow": Setting(
            "Compare adaptive polling (shadow only)",
            "System",
            "Record bounded would-be reads only. Actual bridge polling, authentication, budgets and confirmations are unchanged.",
            kind="switch",
        ),
        "adaptive_poll_heating_minutes": Setting(
            "Shadow heating poll maximum",
            "System",
            "Advisory heating cap, at most 60 minutes. Does not change actual reads.",
            15,
            60,
            "min",
        ),
        "adaptive_poll_stable_minutes": Setting(
            "Shadow stable poll maximum",
            "System",
            "Advisory stable cap, at most 90 minutes. Vendor inactivity expiry remains unverified.",
            30,
            90,
            "min",
        ),
    }
)
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
            "Supported native thermostat target during permitted nights/weekends; does not prove achieved tank temperature.",
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
            "Optional heat requires verified raw circuit measurement and useful monetary benefit. Independent of the peak policy. 12-hour Override stays 70.",
            kind="switch",
        ),
        "peak_heating_policy": Setting(
            "Heating during peak periods",
            "Everyday",
            "The Never option takes priority over routine solar opportunities. Solar-only requires verified raw circuit power, fresh grid and all qualifications. Explicit owner override/native protections remain independent.",
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
CATALOG["adaptive_polling_enabled"] = Setting(
    "Send adaptive cloud scheduling plans",
    "System",
    "Disabled until independent review and supervised validation. Sends bounded expiring hints only; the bridge needs its separate enabled and qualified options. Fixed fallback and every cloud/command guard remain.",
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
assert set(CATALOG) == set(DEFAULT_OPTIONS)
# 0.8.0 interface groups. Everyday: what a homeowner adjusts. Advanced: tariff,
# forecasts, economic and model assumptions. System: commissioning, safety
# timing, budgets and verification (most need automatic control OFF to edit).
# Retired: no control any more (no production effect, see SETTINGS_AUDIT.md);
# the stored value is kept, validated and restored by a rollback.
GROUPS = ("Everyday", "Advanced", "System")
RETIRED = frozenset(key for key, meta in CATALOG.items() if meta.group == "Retired")
# 0.9.0: every Everyday setting belonged to the retired planner; the group stays
# so saved menus and dashboards keep working, and may be empty.
assert {meta.group for meta in CATALOG.values()} <= {*GROUPS, "Retired"}

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
        "meter_verified": True,
        "tariff_verified": True,
        "import_positive": False,
        "tariff_clock": "standard",
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
        "controller_three_state_qualified",
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
        # 0.9.1 (audit M4): the forecast switch decides whether EMHASS is used
        # at all and is a commissioning requirement, not a preference.
        "forecast_enabled",
        "heater_meter_verification",
        "adaptive_polling_shadow",
        "adaptive_polling_enabled",
        "adaptive_poll_heating_minutes",
        "adaptive_poll_stable_minutes",
        "optional_heat_margin_aud_per_kwh",
        "pause_min_saving_aud",
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
        "controller_three_state_qualified",
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
        "forecast_enabled",
        "sources",
        "optional_heat_margin_aud_per_kwh",
        "pause_min_saving_aud",
        "heater_meter_verification",
    }
)
PRESERVE_ON_RESTORE = PRESERVE_ON_RESTORE | _DUAL_PROTECTED
LOCKED_WHILE_ACTIVE = LOCKED_WHILE_ACTIVE | _DUAL_PROTECTED
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


LOCKED_WHILE_ACTIVE = LOCKED_WHILE_ACTIVE | {"adaptive_polling_enabled"}
PRESERVE_ON_RESTORE = PRESERVE_ON_RESTORE | {
    "time_zone",
    "daytime_start",
    "storage_ready_time",
    "baseline_start",
}
LOCKED_WHILE_ACTIVE = LOCKED_WHILE_ACTIVE | {
    "time_zone",
    "daytime_start",
    "storage_ready_time",
    "baseline_start",
}
