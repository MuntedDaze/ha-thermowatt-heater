"""Only sensors: estimates deliberately have no energy-measurement state class."""

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.helpers.device_registry import DeviceInfo

from .naming import RETIRED_SENSORS as RETIRED  # noqa: F401 (re-exported)
from .naming import device_info_fields, entity_id
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
    "peak_start": ("Configured afternoon peak", None),
    "planned_start": ("Hypothetical heating start", None),
    "requests_since_start": ("Observed request attempts", None),
    "observed_requests_per_hour": ("Observed requests per hour", None),
    "storage_target_c": ("Afternoon storage target", "°C"),
    "latest_start": ("Latest continuous heating start", None),
    "current_tariff": ("Current tariff", None),
    "current_price_aud": ("Current import price", "AUD/kWh"),
    "measured_import_kw": ("Measured grid import", "kW"),
    "measured_export_kw": ("Measured grid export", "kW"),
    "forecast_net_surplus_kw": ("Forecast net surplus", "kW"),
    "forecast_age_minutes": ("Forecast age", "min"),
    "decision": ("Decision code", None),
    "heater_element_state": ("Heater element state", None),
    "heater_state_confidence": ("Heater state confidence", None),
    "base_load_kw": ("Base household load excluding hot water", "kW"),
    "measured_pv_ac_kw": ("Measured PV AC output", "kW"),
    "next_tariff_change": ("Next tariff change", None),
    "next_tariff_kind": ("Next tariff period", None),
    "current_tariff_rate_aud": ("Current tariff rate", "AUD/kWh"),
    # 0.9.0: the simplified policy (read-only; the controller alone commands).
    "policy_state": ("Policy wanted state", None),
    "policy_mode": ("Policy mode", None),
    "soft_target": ("Soft target time", None),
    "target_reached": ("Storage target reached", None),
    "heating_hours_needed": ("Heating time needed", "h"),
    "measured_surplus_kw": ("Measured surplus excluding element", "kW"),
    "shadow_command": ("Shadow command", None),
}
TIMESTAMPS = {"peak_start", "planned_start", "latest_start", "next_tariff_change", "soft_target"}
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
    "operating_mode": ("Hot water operating mode", None),
    "guest_mode_ends": ("12hr Override ends", None),
}
CONTROLLER_TIMESTAMPS = {
    "next_heating_start",
    "next_heating_stop",
    "last_command_time",
    "guest_mode_ends",
}


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    entities = [
        ShadowSensor(runtime, entry, key, name, unit) for key, (name, unit) in SENSORS.items()
    ]
    entities += [
        ControllerSensor(runtime, entry, key, name, unit)
        for key, (name, unit) in CONTROLLER_SENSORS.items()
    ]
    entities.append(ThermalStateSensor(runtime, entry))
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
        self.entity_id = entity_id("sensor", name)
        self._attr_native_unit_of_measurement = unit
        self._attr_device_info = DeviceInfo(**device_info_fields(DOMAIN, entry.entry_id))
        if key in TIMESTAMPS:
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


class ThermalStateSensor(ShadowSensor):
    """0.7.0 read-only tank-state ESTIMATE from the bottom-of-tank reading,
    the meter-detected element and the clock. Diagnostics only: it never
    affects heater commands. Attributes separate measured, estimated and
    inferred values, each with its basis and confidence."""

    _attr_icon = "mdi:thermometer-water"

    def __init__(self, runtime, entry):
        super().__init__(
            runtime, entry, "tank_thermal_state", "Tank thermal state (estimate)", None
        )
        from homeassistant.const import EntityCategory

        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        return self.runtime.thermal.state

    @property
    def extra_state_attributes(self):
        from homeassistant.util import dt as dt_util

        return self.runtime.thermal.summary(dt_util.utcnow())
