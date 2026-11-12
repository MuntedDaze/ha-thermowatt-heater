"""Holiday return DATE (0.9.0). Owner input only: nothing here commands the
heater. Holiday mode keeps the heater OFF and ends at 00:00 Hobart local on
this date; the normal policy then resumes (usually Manual 45 °C overnight)."""

from homeassistant.components.date import DateEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .config import DOMAIN
from .naming import device_info_fields, entity_id


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([HolidayReturnDate(entry, hass.data[DOMAIN][entry.entry_id])])


class HolidayReturnDate(DateEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Holiday return date"
    _attr_icon = "mdi:airplane-landing"

    def __init__(self, entry, runtime):
        self.runtime = runtime
        self._attr_unique_id = f"{entry.entry_id}_holiday_return_date"
        self.entity_id = entity_id("date", self._attr_name)
        self._attr_device_info = DeviceInfo(**device_info_fields(DOMAIN, entry.entry_id))

    async def async_added_to_hass(self):
        self.async_on_remove(self.runtime.executor.subscribe(self.async_write_ha_state))

    @property
    def native_value(self):
        return self.runtime.executor.controller.holiday_return_date()

    async def async_set_value(self, value):
        from homeassistant.exceptions import HomeAssistantError

        executor = self.runtime.executor
        if not await executor.async_set_holiday("return", value):
            why = executor.controller.refusal or "invalid_holiday_dates"
            raise HomeAssistantError(f"Holiday dates not saved: {why.replace('_', ' ')}.")
