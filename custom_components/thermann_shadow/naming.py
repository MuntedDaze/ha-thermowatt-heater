"""User-facing names (0.8.0) without changing any identity.

The integration is shown as **Thermann Controller**; its domain stays
``thermann_shadow`` and every entity ID keeps the ``thermann_shadow_`` prefix,
for existing installs (the entity registry keeps IDs) and fresh installs alike
(each entity requests its historical ID instead of deriving one from the new
device name). Renamed entities request the ID of their former name, so
automations, dashboards and history keep working.

Pure module: no Home Assistant imports (the device info is built by callers).
"""

import re

ENTITY_PREFIX = "thermann_shadow"
DEVICE_NAME = "Thermann Controller"
MANUFACTURER = "Unofficial community project (not a Thermann product)"
MODEL = "Hot water controller"
ENTRY_TITLE = "Thermann Controller"
OLD_ENTRY_TITLES = frozenset({"Thermann Shadow"})

# Display name now -> the name the entity ID was first derived from.
LEGACY_NAMES = {
    "Start 12hr Override": "Start guest mode (12 h)",
    "Cancel 12hr Override": "Cancel guest mode",
    "12hr Override ends": "Guest mode ends",
    "Weekend afternoon ready time": "Afternoon comfort preference",
}


def slug(value: str) -> str:
    """HA's slugify for the ASCII names used here."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def object_id(name: str) -> str:
    return f"{ENTITY_PREFIX}_{slug(LEGACY_NAMES.get(name, name))}"


def entity_id(domain: str, name: str) -> str:
    return f"{domain}.{object_id(name)}"


def device_info_fields(domain: str, entry_id: str) -> dict:
    return {
        "identifiers": {(domain, entry_id)},
        "name": DEVICE_NAME,
        "manufacturer": MANUFACTURER,
        "model": MODEL,
    }


# Retired sensors (unique-id suffixes). Their registry entries are removed at
# setup so they do not linger as "unavailable" (see __init__.py).
RETIRED_SENSORS = (
    "simulated_cycle_count",
    "simulated_stop_count",
    "suppressed_switching_episodes",
    "simulated_cost_aud",
    # 0.9.0: the 0.4-0.8 planner's estimates and goals.
    "deadline",
    "comfort_deadline",
    "mixed_model_energy_kwh",
    "modelled_heating_minutes",
    "estimated_import_kwh",
    "estimated_solar_kwh",
    "unmet_model_energy_kwh",
    "estimated_cost_aud",
    "comparison_cost_difference_aud",
    "native_schedule_window",
    "t_comfort_reference_c",
    "morning_threshold_c",
    "planning_target_c",
    "grid_fallback_start",
    "recommended_energy_source",
    "device_clock_check",
    "recommendation",
    "simulated_cycle_state",
    "benefit_of_now_aud",
    "continuing_cost_aud",
    "later_cost_aud",
    "deadline_countdown_minutes",
    "completion_time",
    "forecast_usable_solar_kwh",
    "current_solar_surplus_kw",
    "morning_ready_deadline",
    "afternoon_ready_deadline",
    "morning_readiness",
    "afternoon_readiness",
    "waiting_saving_aud",
    "decision_confidence",
    "native_predicted_cost_aud",
    "native_vs_best_plan_aud",
    "schedule_advisor_suggestion",
)
