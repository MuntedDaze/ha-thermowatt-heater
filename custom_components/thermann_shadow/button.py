"""Restore local recommendations only; dashboard asks for confirmation."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from .config import DOMAIN
from .settings_entity import save


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([RestoreRecommendations(entry)])


class RestoreRecommendations(ButtonEntity):
    _attr_has_entity_name = True
    _attr_name = "Restore recommended preferences"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry):
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_restore_recommended"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Thermann Shadow",
            manufacturer="Community shadow planner",
            model="315 L / 3 kW scenario",
        )

    async def async_press(self):
        await save(self.hass, self.entry, restore=True)
