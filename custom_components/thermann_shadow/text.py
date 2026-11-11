"""Advanced references/custom weekly periods, never device programming."""

from homeassistant.components.text import TextEntity
from .settings_entity import SettingEntity, setup_controls


async def async_setup_entry(hass, entry, async_add_entities):
    setup_controls(hass, entry, async_add_entities, "text", ShadowText)


class ShadowText(SettingEntity, TextEntity):
    _attr_native_max = 10

    def __init__(self, entry, runtime, key):
        super().__init__(entry, runtime, key)
        if key.startswith("controller_"):
            self._attr_native_max = 64

    @property
    def native_value(self):
        return self.current

    async def async_set_value(self, value):
        await self.write(value)
