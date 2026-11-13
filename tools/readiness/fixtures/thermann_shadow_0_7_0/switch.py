"""Preference toggles, plus the controller master switch.

No switch operates the water heater directly. "Automatic heater control" only
allows the commissioned controller to decide; turning it OFF stops all
automatic commands immediately and never changes the heater mode.
"""

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .config import DOMAIN
from .settings_entity import SettingEntity, setup_controls


async def async_setup_entry(hass, entry, async_add_entities):
    setup_controls(hass, entry, async_add_entities, "switch", ShadowSwitch)
    async_add_entities([AutomaticControl(entry, hass.data[DOMAIN][entry.entry_id])])


class ShadowSwitch(SettingEntity, SwitchEntity):
    @property
    def is_on(self):
        return self.current

    async def async_turn_on(self, **kwargs):
        await self.write(True)

    async def async_turn_off(self, **kwargs):
        await self.write(False)


class AutomaticControl(SwitchEntity):
    """Master enable. Refuses to turn on until commissioning is complete."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_name = "Automatic heater control"
    _attr_icon = "mdi:robot"

    def __init__(self, entry, runtime):
        self.entry, self.runtime = entry, runtime
        self._attr_unique_id = f"{entry.entry_id}_automatic_control"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Thermann Shadow",
            manufacturer="Community shadow planner",
            model="315 L / 3 kW scenario",
        )

    async def async_added_to_hass(self):
        self.async_on_remove(self.runtime.executor.subscribe(self.async_write_ha_state))

    @property
    def is_on(self):
        return self.runtime.executor.controller.enabled

    @property
    def extra_state_attributes(self):
        executor = self.runtime.executor
        return {
            "commissioning_missing": executor.cfg.missing_commissioning(),
            "state": executor.controller.state,
            "turning_off_changes_heater_mode": False,
        }

    async def async_turn_on(self, **kwargs):
        await self.runtime.executor.async_set_enabled(True)

    async def async_turn_off(self, **kwargs):
        await self.runtime.executor.async_set_enabled(False)
