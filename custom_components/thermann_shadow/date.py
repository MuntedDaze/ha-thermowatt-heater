"""Holiday departure and return DATES (0.9.0). Owner inputs only: nothing here
commands the heater. Holiday mode starts at 00:00 Hobart local on the
departure date (at once for today's date) and keeps the heater OFF; it ends at
00:00 Hobart local on the return date, and the normal policy resumes."""

from homeassistant.components.date import DateEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .config import DOMAIN
from .naming import device_info_fields, entity_id


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            HolidayDate(entry, runtime, "start", "Holiday departure date", "mdi:airplane-takeoff"),
            HolidayDate(entry, runtime, "return", "Holiday return date", "mdi:airplane-landing"),
        ]
    )


class HolidayDate(DateEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry, runtime, which, name, icon):
        self.runtime, self.which = runtime, which
        self._attr_name = name
        self._attr_icon = icon
        suffix = "departure_date" if which == "start" else "return_date"
        self._attr_unique_id = f"{entry.entry_id}_holiday_{suffix}"
        self.entity_id = entity_id("date", name)
        self._attr_device_info = DeviceInfo(**device_info_fields(DOMAIN, entry.entry_id))

    async def async_added_to_hass(self):
        self.async_on_remove(self.runtime.executor.subscribe(self.async_write_ha_state))

    @property
    def native_value(self):
        controller = self.runtime.executor.controller
        if self.which == "start":
            return controller.holiday_start_date()
        return controller.holiday_return_date()

    async def async_set_value(self, value):
        from homeassistant.exceptions import HomeAssistantError

        executor = self.runtime.executor
        if not await executor.async_set_holiday(self.which, value):
            why = executor.controller.refusal or "invalid_holiday_dates"
            raise HomeAssistantError(f"Holiday dates not saved: {why.replace('_', ' ')}.")
