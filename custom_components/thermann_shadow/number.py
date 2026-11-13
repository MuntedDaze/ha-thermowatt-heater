"""Validated shadow-model numeric preferences, never heater setpoints."""

from homeassistant.components.number import NumberEntity, NumberMode
from .config import WHOLE_NUMBER_OPTIONS
from .settings_entity import SettingEntity, setup_controls


async def async_setup_entry(hass, entry, async_add_entities):
    setup_controls(hass, entry, async_add_entities, "number", ShadowNumber)


class ShadowNumber(SettingEntity, NumberEntity):
    _attr_mode = NumberMode.BOX
    _attr_native_step = 0.01

    def __init__(self, entry, runtime, key):
        super().__init__(entry, runtime, key)
        self._attr_native_min_value = self.meta.low
        self._attr_native_max_value = self.meta.high
        self._attr_native_unit_of_measurement = self.meta.unit
        if key.endswith("rate"):
            self._attr_native_step = 0.000001
        elif key in WHOLE_NUMBER_OPTIONS:
            self._attr_native_step = 1

    @property
    def native_value(self):
        return self.current

    async def async_set_native_value(self, value):
        await self.write(value)
