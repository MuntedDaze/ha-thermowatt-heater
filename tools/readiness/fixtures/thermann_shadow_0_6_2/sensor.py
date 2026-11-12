"""Only sensors: estimates deliberately have no energy-measurement state class."""

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.helpers.device_registry import DeviceInfo

from .config import DOMAIN

SENSORS = {
    "controller": ("Controller", None),
    "temperature": ("Bottom temperature", "°C"),
    "target": ("Reported target", "°C"),
    "pv": ("Measured PV", "kW"),
    "house": ("Measured house load", "kW"),
    "grid": ("Measured signed grid", "kW"),
    "measured_net_export_kw": ("Derived net export", "kW"),
    "cloud_health": ("Cloud health", None),
    "status_age_minutes": ("Status age", "min"),
    "deadline": ("Planning deadline", None),
    "comfort_deadline": ("Comfort deadline", None),
    "peak_start": ("Configured afternoon peak", None),
    "planned_start": ("Hypothetical heating start", None),
    "mixed_model_energy_kwh": ("Mixed tank energy estimate", "kWh"),
    "modelled_heating_minutes": ("Heating time estimate", "min"),
    "estimated_import_kwh": ("Plan import estimate", "kWh"),
    "estimated_solar_kwh": ("Plan solar estimate", "kWh"),
    "unmet_model_energy_kwh": ("Modelled energy shortfall", "kWh"),
    "estimated_cost_aud": ("Plan cost estimate", "AUD"),
    "comparison_cost_difference_aud": ("Scenario cost difference", "AUD"),
    "requests_since_start": ("Observed request attempts", None),
    "observed_requests_per_hour": ("Observed requests per hour", None),
    "native_schedule_window": ("Reported Schedule window", None),
    "t_comfort_reference_c": ("T Comfort reference", "°C"),
    "morning_threshold_c": ("Morning comfort threshold", "°C"),
    "storage_target_c": ("Afternoon storage target", "°C"),
    "planning_target_c": ("Next decision threshold", "°C"),
    "latest_start": ("Latest continuous heating start", None),
    "grid_fallback_start": ("Off peak fallback start", None),
    "current_tariff": ("Current tariff", None),
    "current_price_aud": ("Current import price", "AUD/kWh"),
    "recommended_energy_source": ("Recommended energy source", None),
    "device_clock_check": ("Device clock check", None),
    "measured_import_kw": ("Measured grid import", "kW"),
    "measured_export_kw": ("Measured grid export", "kW"),
    "recommendation": ("Recommendation", None),
    "simulated_cycle_state": ("Simulated cycle state", None),
    "benefit_of_now_aud": ("Benefit of heating now", "AUD"),
    "continuing_cost_aud": ("Continuous cycle cost now", "AUD"),
    "later_cost_aud": ("Continuous cycle cost later", "AUD"),
    "forecast_net_surplus_kw": ("Forecast net surplus", "kW"),
    "forecast_age_minutes": ("Forecast age", "min"),
    "deadline_countdown_minutes": ("Comfort countdown", "min"),
    "completion_time": ("Simulated completion", None),
    "decision": ("Decision code", None),
    "forecast_usable_solar_kwh": ("Forecast usable solar before deadline", "kWh"),
    # 0.4.0: actual-versus-hypothetical heating, de-embedded load, tariff, readiness.
    "heater_element_state": ("Heater element state", None),
    "heater_state_confidence": ("Heater state confidence", None),
    "base_load_kw": ("Base household load excluding hot water", "kW"),
    "measured_pv_ac_kw": ("Measured PV AC output", "kW"),
    "current_solar_surplus_kw": ("Hypothetical solar surplus if heater off", "kW"),
    "next_tariff_change": ("Next tariff change", None),
    "next_tariff_kind": ("Next tariff period", None),
    "current_tariff_rate_aud": ("Current tariff rate", "AUD/kWh"),
    "morning_ready_deadline": ("Morning ready deadline", None),
    "afternoon_ready_deadline": ("Afternoon ready deadline", None),
    "morning_readiness": ("Morning readiness", None),
    "afternoon_readiness": ("Afternoon readiness", None),
    "waiting_saving_aud": ("Saving by waiting", "AUD"),
    "decision_confidence": ("Decision confidence", None),
    "native_predicted_cost_aud": ("Native Schedule predicted cost", "AUD"),
    "native_vs_best_plan_aud": ("Native Schedule extra cost vs best plan", "AUD"),
    "schedule_advisor_suggestion": ("Schedule advisor today", None),
}
# Retired in 0.4.0 (described a non-existent executor). HA keeps their registry
# entries as unavailable until the owner removes them; see UPGRADING_0_4_0.md.
RETIRED = (
    "simulated_cycle_count",
    "simulated_stop_count",
    "suppressed_switching_episodes",
    "simulated_cost_aud",
)


CONTROLLER_SENSORS = {
    "controller_state": ("Automatic control state", None),
    "controller_reason": ("Automatic control reason", None),
    "thermann_mode": ("Thermann mode", None),
    "thermann_target": ("Thermann target", "°C"),
    "next_action": ("Next intended action", None),
    "next_heating_start": ("Next heating start", None),
    "next_heating_stop": ("Next heating stop", None),
    "last_command": ("Last command", None),
    "last_command_result": ("Last command result", None),
    "last_command_time": ("Last command time", None),
    "commands_last_24h": ("Commands in last 24 hours", None),
    "requests_last_24h": ("Cloud requests in last 24 hours", None),
    "fault": ("Controller fault", None),
}
CONTROLLER_TIMESTAMPS = {"next_heating_start", "next_heating_stop", "last_command_time"}


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    entities = [
        ShadowSensor(runtime, entry, key, name, unit) for key, (name, unit) in SENSORS.items()
    ]
    entities += [
        ControllerSensor(runtime, entry, key, name, unit)
        for key, (name, unit) in CONTROLLER_SENSORS.items()
    ]
    async_add_entities(entities)


class ShadowSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_icon = "mdi:water-boiler"

    def __init__(self, runtime, entry, key, name, unit):
        self.runtime = runtime
        self.key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Thermann Shadow",
            manufacturer="Community shadow planner",
            model="315 L / 3 kW scenario",
        )
        if key in {
            "deadline",
            "comfort_deadline",
            "peak_start",
            "planned_start",
            "latest_start",
            "grid_fallback_start",
            "completion_time",
            "next_tariff_change",
            "morning_ready_deadline",
            "afternoon_ready_deadline",
        }:
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

    async def async_added_to_hass(self):
        self.async_on_remove(self.runtime.subscribe(self.async_write_ha_state))

    @property
    def native_value(self):
        return self.runtime.values.get(self.key)

    @property
    def extra_state_attributes(self):
        return self.runtime.details if self.key == "controller" else None


class ControllerSensor(ShadowSensor):
    """Production controller status (read-only; no entity here commands anything)."""

    _attr_icon = "mdi:robot-outline"

    def __init__(self, runtime, entry, key, name, unit):
        super().__init__(runtime, entry, key, name, unit)
        self._attr_device_class = (
            SensorDeviceClass.TIMESTAMP if key in CONTROLLER_TIMESTAMPS else None
        )

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self.runtime.executor.subscribe(self.async_write_ha_state))

    @property
    def native_value(self):
        return self.runtime.executor.values().get(self.key)

    @property
    def extra_state_attributes(self):
        return self.runtime.executor.details() if self.key == "controller_state" else None
