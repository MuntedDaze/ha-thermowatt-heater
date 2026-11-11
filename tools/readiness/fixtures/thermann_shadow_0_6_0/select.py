"""Clock/period interpretation controls; never device modes."""

from homeassistant.components.select import SelectEntity
from .settings_entity import SettingEntity, setup_controls


async def async_setup_entry(hass, entry, async_add_entities):
    setup_controls(hass, entry, async_add_entities, "select", ShadowSelect)


class ShadowSelect(SettingEntity, SelectEntity):
    @property
    def options(self):
        return list(self.meta.choices)

    @property
    def current_option(self):
        return self.current

    async def async_select_option(self, option):
        await self.write(option)
