"""Holiday departure (0.7.0). Owner input only: nothing here commands the
heater. The return is a DATE since 0.9.0 (date.py)."""

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.util import dt as dt_util

from .naming import device_info_fields, entity_id
from .config import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            HolidayDate(entry, runtime, "start", "Holiday departure", "mdi:airplane-takeoff"),
        ]
    )


class HolidayDate(DateTimeEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry, runtime, which, name, icon):
        self.runtime, self.which = runtime, which
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_holiday_{which}"
        self.entity_id = entity_id("datetime", name)
        self._attr_device_info = DeviceInfo(**device_info_fields(DOMAIN, entry.entry_id))

    async def async_added_to_hass(self):
        self.async_on_remove(self.runtime.executor.subscribe(self.async_write_ha_state))

    @property
    def native_value(self):
        value = self.runtime.executor.controller.holiday_start
        return dt_util.parse_datetime(value) if value else None

    async def async_set_value(self, value):
        from homeassistant.exceptions import HomeAssistantError

        executor = self.runtime.executor
        if not await executor.async_set_holiday(self.which, value):
            why = executor.controller.refusal or "invalid_holiday_dates"
            raise HomeAssistantError(f"Holiday dates not saved: {why.replace('_', ' ')}.")
