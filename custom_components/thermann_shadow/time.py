"""Local model deadlines and tariff times; no heater clock writes."""

from datetime import time
from homeassistant.components.time import TimeEntity
from .settings_entity import SettingEntity, setup_controls


async def async_setup_entry(hass, entry, async_add_entities):
    setup_controls(hass, entry, async_add_entities, "time", ShadowTime)


class ShadowTime(SettingEntity, TimeEntity):
    @property
    def native_value(self):
        return time.fromisoformat(self.current)

    async def async_set_value(self, value):
        if value.second or value.microsecond or value.tzinfo is not None:
            from homeassistant.exceptions import HomeAssistantError

            raise HomeAssistantError("Use whole-minute HH:MM times for shadow preferences.")
        await self.write(value.strftime("%H:%M"))
