"""Presentation only: form layout, help and reversible display-unit conversion.

Stored option keys, native setting entities and the tariff/controller model stay
unchanged. This module has no Home Assistant dependency so conversion and schedule
editing can be checked independently of the frontend.
"""

from decimal import Decimal
import json

from .config import DEFAULT_OPTIONS, _minute, parse_options
from .settings import CATALOG


MENUS = {
    "init": ("hot_water", "electricity", "solar_meters", "advanced"),
    "electricity": ("prices", "peak_times", "schedule", "tariff_json"),
    "solar_meters": ("solar", "sources"),
    "advanced": ("equipment", "polling", "commissioning", "bridge_sources"),
}
PAGES = {
    "hot_water": (
        "baseline_c",
        "normal_storage_c",
        "solar_boost_c",
        "optional_solar_boost",
        "peak_heating_policy",
        "completion_margin_minutes",
        "daytime_start",
        "storage_ready_time",
        "baseline_start",
    ),
    "prices": (
        "tariff_profile",
        "time_zone",
        "tariff_clock",
        "off_peak_rate",
        "peak_rate",
        "shoulder_rate",
        "feed_in_rate",
        "tariff_verified",
    ),
    "peak_times": (
        "peak_morning_start",
        "peak_morning_end",
        "peak_evening_start",
        "peak_evening_end",
        "weekend_peak",
    ),
    "tariff_json": ("tariff_periods",),
    "solar": (
        "forecast_enabled",
        "forecast_uncertainty",
        "forecast_house_margin_kw",
        "forecast_max_age_minutes",
        "pv_ac_limit_kw",
        "meter_verified",
        "import_positive",
    ),
    "equipment": (
        "tank_litres",
        "element_kw",
        "boost_useful_fraction",
        "boost_min_saving_aud",
        "optional_heat_margin_aud_per_kwh",
        "pause_min_saving_aud",
    ),
    "polling": (
        "adaptive_polling_shadow",
        "adaptive_polling_enabled",
        "event_aware_polling_enabled",
        "owner_change_check_minutes",
        "adaptive_poll_heating_minutes",
        "adaptive_poll_stable_minutes",
        "status_max_age_minutes",
        "grid_max_age_seconds",
    ),
    "commissioning": (
        "controller_command_topic",
        "controller_three_state_qualified",
        "controller_four_state_qualified",
        "heater_meter_verification",
        "learned_planning_enabled",
        "learning_hardware_qualified",
        "controller_max_commands_per_day",
        "controller_max_requests_per_day",
        "controller_confirmation_timeout_minutes",
        "controller_notify_service",
    ),
}

# Labels/help belong to the forms, not CATALOG names (which derive native entity
# IDs). Renaming a form must never rename an existing entity or change its unit.
FIELDS = {
    "baseline_c": (
        "Night and weekend temperature",
        "Thermostat target during permitted baseline hours. Your saved household choice is retained. Only supported temperatures are offered; a setpoint does not prove whole-tank temperature or hygiene compliance. Follow appliance and plumbing requirements.",
    ),
    "normal_storage_c": (
        "Normal weekday storage temperature",
        "Required weekday thermostat target, for example 62°C in the owner's agreed strategy. It must be at least the baseline. This is a target, not a guarantee of hot-water quantity.",
    ),
    "solar_boost_c": (
        "Optional solar storage temperature",
        "Upper target for worthwhile extra solar heating, for example 70°C. Must be at least normal storage. Equal targets avoid a separate top-up; choosing a target alone does not enable boosting.",
    ),
    "optional_solar_boost": (
        "Enable optional solar boost",
        "Allow extra storage only with commissioned hot-water circuit measurement and all economic and safety checks. Leave off if you do not want extra heat. Required storage still works without a circuit meter; the separate 12-hour Override is unchanged.",
    ),
    "peak_heating_policy": (
        "Heating during peak periods",
        "Never schedule heating takes priority even with high solar export. The solar-only choice requires verified circuit power and every existing safeguard. Owner overrides and native protective cycles remain possible. Cloud OFF is not proof of zero electricity use.",
    ),
    "completion_margin_minutes": (
        "Aim to finish heating this much early",
        "Minutes reserved before the required finish time; 30 minutes is a useful planning starting point. Required heating may continue to the hard peak boundary. This is a planning allowance, not extra permission to heat during peak.",
    ),
    "daytime_start": (
        "Weekday heating window starts",
        "Household local time, for example 09:00. Used when the plan has no peak deadline. Must be before the ready time. Tariff peak boundaries take priority on time-of-use plans.",
    ),
    "storage_ready_time": (
        "Weekday hot water ready by",
        "Household local time, for example 16:00, when there is no peak deadline. After the window starts and before the baseline returns. A planning goal, not a temperature or hygiene guarantee.",
    ),
    "baseline_start": (
        "Return to night temperature at",
        "Household local time, for example 21:00, when there is no peak deadline. Must follow the ready time. The peak policy still applies.",
    ),
    "tariff_profile": (
        "Electricity plan type",
        "Flat rate uses the off-peak/flat price all day, with no peak periods. The Aurora example uses the editable two-peak schedule; verify it against your retail contract. Custom uses the guided weekly/seasonal schedule. Selecting a plan does not verify it.",
    ),
    "time_zone": (
        "Household time zone",
        "Search for your IANA zone, for example Australia/Hobart or Australia/Perth. New setup uses Home Assistant's zone. Household times follow this zone; the separate tariff clock decides whether electricity periods follow daylight saving.",
    ),
    "tariff_clock": (
        "Clock used by your electricity contract",
        "Local time follows daylight saving in the chosen zone. Fixed standard time keeps its standard UTC offset all year (for example AEST UTC+10 in Hobart). During summer those tariff times can differ from the wall clock. Check your retailer's contract.",
    ),
    "off_peak_rate": (
        "Off-peak or flat electricity price",
        "Australian cents per kWh imported from the grid, for example 25 means $0.25/kWh. Off-peak is the usually cheaper period; on a flat plan this price applies all day. Use your actual retail usage price, not the daily supply charge or a network tariff.",
    ),
    "peak_rate": (
        "Peak electricity price",
        "Australian cents per kWh during peak periods, usually the expensive hours. Example: 40 means $0.40/kWh. Used only by periods marked peak; the peak-heating policy still applies even if another price happens to be cheaper.",
    ),
    "shoulder_rate": (
        "Shoulder electricity price",
        "Australian cents per kWh in periods between peak and off-peak, if your contract has them. Example: 30 means $0.30/kWh. Used only by custom periods marked shoulder; otherwise retained without effect.",
    ),
    "feed_in_rate": (
        "Payment for exported solar electricity",
        "Australian cents per kWh your retailer pays for exported solar, for example 8 means $0.08/kWh. Using solar for hot water gives up this payment, so the controller includes it as a cost. Use your contract's rate; time-varying export prices are not modelled.",
    ),
    "tariff_verified": (
        "I have checked my electricity contract",
        "Confirm only after checking retail prices, every period, weekends, seasons, time zone and tariff clock. Automatic control needs this verification. Saving a form is not verification; changing a price does not check the bill for you.",
    ),
    "weekend_peak": (
        "Apply the example peak hours on weekends too",
        "Only affects the Aurora-style two-peak plan. Off means all weekend hours are off-peak. Follow your actual contract; custom schedules specify weekdays separately.",
    ),
    "tariff_periods": (
        "Advanced schedule data (JSON)",
        "Expert alternative to the guided schedule editor. Days are 0=Monday to 6=Sunday; months are 1–12; start/end are HH:MM. kind is off_peak, shoulder or peak. Optional rate is dollars/kWh, not the cents shown elsewhere. Every minute of every day/month must be covered exactly once. Nothing saves if invalid.",
    ),
    "forecast_enabled": (
        "Use solar and household forecasts",
        "Use timestamped predictions of solar production and household demand to choose economical required heating windows. Optional: leave off without solar/EMHASS. Missing or old forecasts cause conservative nominal planning, not assumed free solar. Optional boost still requires a commissioned circuit meter.",
    ),
    "forecast_uncertainty": (
        "Forecast safety allowance",
        "Percentage to subtract from predicted solar and add to predicted household demand. Example: 25% is stored as 0.25. Larger values are more cautious; forecasts never guarantee surplus electricity.",
    ),
    "forecast_house_margin_kw": (
        "Extra allowance for household appliances",
        "Additional kW reserved for competing appliances beyond the forecast. Example: 0.3 kW is 300 W. Higher values reduce assumed solar available for heating.",
    ),
    "forecast_max_age_minutes": (
        "Ignore forecasts older than",
        "Minutes since the forecast was generated, not when an old forecast was republished. For 30-minute EMHASS updates use at least 35 minutes; 120 is a starting example. Old forecasts are ignored rather than treated as future solar.",
    ),
    "pv_ac_limit_kw": (
        "Maximum usable inverter output",
        "Combined AC output limit in kW for the inverter represented by your solar readings. Example: a 5 kW inverter can have more than 5 kW of panels. Forecast output above this limit is clipped; use the inverter rating, not panel capacity.",
    ),
    "meter_verified": (
        "Grid meter readings have been checked",
        "Confirm only after checking net grid power, units, sign and freshness with a known load/export test. This verifies the grid meter, not the separate hot-water circuit meter. Never turn it on merely to clear a warning.",
    ),
    "import_positive": (
        "Positive grid power means buying electricity",
        "On: positive net power is grid import and negative is export. Off: positive is export. Verify using a known household load and your meter's documentation; a reversed sign can make costly import look like surplus solar.",
    ),
    "tank_litres": (
        "Hot-water tank capacity",
        "Nominal litres from the appliance label, for example 315 L. Used for conservative heating estimates, not measured hot-water availability. Changing it clears learned-planning hardware qualification.",
    ),
    "element_kw": (
        "Heater element rating",
        "Nominal electrical kW from the appliance label, for example 3 kW. Without a circuit meter this estimates heating time only; it never proves the element is on. Changing it clears learned-planning hardware qualification.",
    ),
    "boost_useful_fraction": (
        "Extra stored heat likely to be used",
        "Estimated percentage of extra boosted heat used before the next cheap heating opportunity. Example: 90%. Lower values make extra boosting less attractive; 0% prevents it. This assumption is not learned evidence.",
    ),
    "boost_min_saving_aud": (
        "Minimum saving for an extra solar boost",
        "Australian dollars expected to be saved per boost, for example $0.10. Avoids extra commands for trivial benefit. The per-kWh margin and all measured-power guards also apply.",
    ),
    "optional_heat_margin_aud_per_kwh": (
        "Minimum saving per unit of optional heat",
        "Australian cents per kWh saved against off-peak grid heating, including lost solar export income. Example: 2 means $0.02/kWh. This does not relax circuit-measurement or grid-import checks.",
    ),
    "pause_min_saving_aud": (
        "Minimum saving before waiting for a better window",
        "Australian dollars a later window must save, for example $0.30. Heating must still fit before the planning deadline. Increasing this reduces changes for small estimated savings.",
    ),
    "adaptive_polling_shadow": (
        "Preview adaptive cloud checks",
        "Record when adaptive polling would read the cloud, without changing actual bridge requests. Safe starting mode for comparison; it does not enable adaptive polling or automatic heating.",
    ),
    "adaptive_polling_enabled": (
        "Allow adaptive cloud checks",
        "Advanced, default off. Requires independent review, supervised validation and the bridge's separate enabled/qualified options. Sends bounded expiring polling hints; original fixed fallback, authentication, request budgets and command confirmations remain.",
    ),
    "event_aware_polling_enabled": (
        "Allow longer checks during quiet periods",
        "Advanced, default off. Requires adaptive polling and a qualified bridge. A confirmed baseline/OFF period can be checked less often, while temperatures still expire normally. App changes may be detected later, and brief changes can be missed. Command-prior checks and confirmation are unchanged.",
    ),
    "owner_change_check_minutes": (
        "Longest quiet-period check interval",
        "Minutes between ordinary observations with healthy cloud, 30–90. Start with 60 only after qualification. Longer saves requests but delays detecting app changes; outages delay them further. Only used when longer quiet checks are enabled.",
    ),
    "adaptive_poll_heating_minutes": (
        "Preview: longest check interval while heating",
        "Minutes, up to 60, used by the advisory polling model. This preview setting alone does not change actual cloud reads. Use the reviewed bridge and actual polling telemetry to assess real requests.",
    ),
    "adaptive_poll_stable_minutes": (
        "Preview: longest check interval while stable",
        "Minutes, up to 90, used by the advisory polling model. This alone does not change actual cloud reads; vendor inactivity expiry remains unverified.",
    ),
    "status_max_age_minutes": (
        "Maximum age of temperature used for planning",
        "Minutes before a cloud heater observation is too old for temperature-sensitive planning; 45 is the existing starting value for 30-minute fixed checks. This does not schedule a refresh or relax the bridge's exact-prior command checks. Quiet holds use separate bounded rules.",
    ),
    "grid_max_age_seconds": (
        "Maximum age of local power readings",
        "Seconds before local grid observations are considered stale; 120 is an example. Missing or stale data resets economic holds and cannot authorise solar-only heating. Changing this does not trigger cloud requests.",
    ),
    "controller_command_topic": (
        "Bridge command address (MQTT topic)",
        "Commissioning only. Copy the exact mode-command topic announced by your existing bridge. Blank prevents controller commands. Do not guess it or point at another appliance; keep automatic control off while changing it.",
    ),
    "controller_three_state_qualified": (
        "Legacy OFF / 45 / 70 command tests completed",
        "Historical commissioning record retained for existing installations. Set only after separately approved supervised tests, including owner-change refusal. It does not replace four-state qualification or authorise heater operation.",
    ),
    "controller_four_state_qualified": (
        "OFF / 45 / 62 / 70 command tests completed",
        "Commissioning only, default off. Set only after separately approved supervised testing of every required transition and refusal case. This record does not itself authorise automatic control or physical operation.",
    ),
    "heater_meter_verification": (
        "Hot-water meter commissioning record",
        "Expert commissioning record: verified_entity_id|W or verified_entity_id|kW. Requires an exclusive circuit, correct signed units, reporting cadence and OFF/ON/outage tests. Leave blank for CT-free operation. A saved record is not proof the meter is currently available; remapping clears it.",
    ),
    "learned_planning_enabled": (
        "Use qualified heating-performance learning",
        "Advanced, default off. Requires real independent measured sessions, held-out accuracy and hardware qualification. A conservative learned rate may start required heating earlier; it cannot delay heating beyond nominal/live-power planning. Learning cannot establish whole-tank temperature.",
    ),
    "learning_hardware_qualified": (
        "Meter and heater checked for learning",
        "Commissioning gate, default off. Confirm only using real qualified measurements, never synthetic tests. Changing the power mapping, its commissioned units, tank capacity or element rating clears this gate.",
    ),
    "controller_max_commands_per_day": (
        "Optional command budget per 24 hours",
        "Whole commands in a rolling 24 hours; 6 is the existing starting value. Optional solar starts stop at this budget. Essential transitions have the existing extra allowance, and OFF is not blocked by this optional budget. This is not a new permission to issue commands.",
    ),
    "controller_max_requests_per_day": (
        "Cloud request budget per 24 hours",
        "Whole locally accounted HTTP attempts in a rolling 24 hours; 220 is the existing starting value. Commands are refused when this safety budget is exhausted. Polling, authentication and confirmation all cost requests; this setting does not bypass bridge limits.",
    ),
    "controller_confirmation_timeout_minutes": (
        "Time allowed to confirm a command",
        "Minutes before an unconfirmed command fault-locks automatic control; 65 is the existing starting value. Allow at least a normal poll interval plus margin. A timeout does not prove that a command failed or safely permit a blind retry.",
    ),
    "controller_notify_service": (
        "Phone notification service",
        "Optional Home Assistant notify service name, for example mobile_app_jacobs_phone, without notify. in front. Blank keeps Home Assistant's persistent notifications only. Choose an existing notification service; saving this field sends no message.",
    ),
}
for _key, _label in (
    ("peak_morning_start", "Morning peak starts"),
    ("peak_morning_end", "Morning peak ends"),
    ("peak_evening_start", "Afternoon peak starts"),
    ("peak_evening_end", "Afternoon peak ends"),
):
    FIELDS[_key] = (
        _label,
        "Only for the Aurora-style two-peak plan. Time uses your tariff clock, which may differ from the household wall clock in summer. All four times must increase in order. Check your retail contract; custom plans use the guided schedule instead.",
    )

SOURCES = {
    "heater": (
        "Heater temperature and target",
        "Select the existing Thermann bridge water-heater entity. Reads its temperature attributes only; selecting it sends no command. Cloud status does not prove physical element ON/OFF.",
    ),
    "mode": (
        "Heater's reported operating mode",
        "Select the bridge's vendor-mode sensor, which distinguishes Manual, OFF and other native modes. Required for owner-change protection and exact-prior checks; do not substitute an inferred power status.",
    ),
    "last_poll": (
        "Last successful cloud check",
        "Select the bridge's last-successful-poll timestamp sensor. It must describe a real successful observation, not a template's update time. An old observation cannot be treated as fresh.",
    ),
    "cloud_health": (
        "Bridge cloud connection status",
        "Select the existing bridge cloud-health sensor. Faults and outages conservatively restrict control; choosing a different label cannot clear a real fault.",
    ),
    "requests": (
        "Bridge's total cloud request attempts",
        "Select the bridge local-lifetime request-attempt sensor, including persistent/complete accounting attributes. Used by request budgets; not a manually reset daily counter.",
    ),
    "grid": (
        "Net power bought from or sent to the grid",
        "Optional signed W or kW net grid sensor. Verify its positive direction below. Buying and exporting must have opposite signs; an unsigned consumption sensor is unsuitable. Basic tariff operation can run without it.",
    ),
    "pv": (
        "Solar panel production",
        "Optional solar-production W/kW sensor, for display and forecast correction. Panel/DC production is not evidence of usable AC surplus and cannot verify the heater element.",
    ),
    "house": (
        "Whole-house electricity use",
        "Optional household W/kW consumption sensor, for display. This does not replace net grid power or the dedicated hot-water circuit meter.",
    ),
    "import_energy": (
        "Total electricity bought from the grid",
        "Optional cumulative kWh import sensor retained for reference. It does not authorise heater commands or prove current circuit power.",
    ),
    "export_energy": (
        "Total electricity sent to the grid",
        "Optional cumulative kWh export sensor retained for reference. It does not prove current solar surplus.",
    ),
    "forecast_pv": (
        "Forecast solar production",
        "Optional EMHASS solar-forecast series, or supported buffered Forecast.Solar watts, with its original forecast_generated_at timestamp. Predicts future production, not guaranteed spare power. Leave unmapped when forecasts are off.",
    ),
    "forecast_load": (
        "Forecast household electricity use",
        "Optional timestamped EMHASS household-load forecast or supported measured baseline. Used with solar forecasts; neither forecast is required for basic tariff heating. Stale forecasts are ignored.",
    ),
    "pv_ac": (
        "Inverter's usable AC output",
        "Optional W/kW AC-output sensor, consistent with the grid meter. Existing unmapped installations retain the legacy GoodWe total-power fallback; map your actual inverter for other equipment. Do not substitute panel/DC power.",
    ),
    "heater_power": (
        "Dedicated hot-water circuit power (optional)",
        "Optional raw signed W/kW active-power entity for the exclusive heater circuit, from any validated meter. Do not use sensor.em_hot_water_power or a dashboard template. Leave unmapped before the CT is installed. Required storage still works; optional solar-only boost needs commissioning. A failed commissioned meter is a fault, not measured zero.",
    ),
    "heater_energy": (
        "Dedicated hot-water circuit energy (optional)",
        "Optional raw cumulative import-energy Wh/kWh entity for the same circuit. Keep the power sign unchanged; energy must be validated cumulative import. This improves measurements and does not control a relay.",
    ),
}

SCALES = {
    **{
        key: 100
        for key in (
            "off_peak_rate",
            "peak_rate",
            "shoulder_rate",
            "feed_in_rate",
            "optional_heat_margin_aud_per_kwh",
        )
    },
    "forecast_uncertainty": 100,
    "boost_useful_fraction": 100,
}


def display_value(key, value):
    if key not in SCALES:
        return value
    return float(Decimal(str(value)) * SCALES[key])


def stored_changes(values, submitted):
    """Keep original values exactly on a no-op save, including precise prices."""
    result = {}
    for key, value in submitted.items():
        if value == display_value(key, values[key]):
            result[key] = values[key]
        elif key in SCALES:
            result[key] = float(Decimal(str(value)) / SCALES[key])
        else:
            result[key] = value
    return result


def unit(key):
    if key in {"forecast_uncertainty", "boost_useful_fraction"}:
        return "%"
    if key in SCALES:
        return "c/kWh"
    return CATALOG[key].unit


def schedule_rows(raw):
    """Read without rewriting the stored table or discarding optional fields."""
    return json.loads(raw)


def period_from_form(form, original=None):
    row = dict(original or {})
    row.update(
        days=[int(v) for v in form["days"]],
        start=form["start"][:5],
        end=form["end"][:5],
        kind=form["kind"],
        months=[int(v) for v in form["months"]],
    )
    for key in ("start", "end"):
        minute = _minute(form[key])
        if original and key in original and _minute(original[key]) == minute:
            row[key] = original[key]
    if form["use_rate"]:
        previous = row.get("rate")
        shown = display_value("off_peak_rate", previous) if previous is not None else None
        row["rate"] = previous if form["rate"] == shown else float(Decimal(str(form["rate"])) / 100)
    else:
        row.pop("rate", None)
    if "months" not in (original or {}) and row["months"] == list(range(1, 13)):
        row.pop("months")
    # Whole-schedule coverage is deliberately checked by the existing parser at Save.
    if not row["days"] or not row.get("months", [1]):
        raise ValueError("tariff_invalid")
    return row


def schedule_changes(values, rows):
    """Only an explicit final Save activates a custom table. Same parser/guards."""
    raw = json.dumps(rows, separators=(",", ":"))
    if rows == schedule_rows(values["tariff_periods"]):
        raw = values["tariff_periods"]
    changes = {"tariff_profile": "custom", "tariff_periods": raw}
    parse_options({**values, **changes})
    return changes


assert set(FIELDS) == {k for k, v in CATALOG.items() if v.group != "Retired"}
assert len([k for keys in PAGES.values() for k in keys]) == len(FIELDS)
assert {k for keys in PAGES.values() for k in keys} == set(FIELDS)
assert set(FIELDS) <= set(DEFAULT_OPTIONS)
