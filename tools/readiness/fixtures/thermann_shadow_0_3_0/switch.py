"""Preference toggles only; no switch operates the water heater."""

from homeassistant.components.switch import SwitchEntity
from .settings_entity import SettingEntity, setup_controls


async def async_setup_entry(hass, entry, async_add_entities):
    setup_controls(hass, entry, async_add_entities, "switch", ShadowSwitch)


class ShadowSwitch(SettingEntity, SwitchEntity):
    @property
    def is_on(self):
        return self.current

    async def async_turn_on(self, **kwargs):
        await self.write(True)

    async def async_turn_off(self, **kwargs):
        await self.write(False)
