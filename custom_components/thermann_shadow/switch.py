"""Preference toggles, plus the controller master switch.

No switch operates the water heater directly. "Automatic heater control" only
allows the commissioned controller to decide; turning it OFF stops all
automatic commands immediately and never changes the heater mode.
"""

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .naming import device_info_fields, entity_id
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
        self.entity_id = entity_id("switch", self._attr_name)
        self._attr_device_info = DeviceInfo(**device_info_fields(DOMAIN, entry.entry_id))

    async def async_added_to_hass(self):
        self.async_on_remove(self.runtime.executor.subscribe(self.async_write_ha_state))

    @property
    def is_on(self):
        return self.runtime.executor.controller.enabled

    @property
    def extra_state_attributes(self):
        executor = self.runtime.executor
        service = executor.notify_service
        return {
            "commissioning_missing": executor.cfg.missing_commissioning(),
            "state": executor.controller.state,
            "turning_off_changes_heater_mode": False,
            # 0.7.1 (audit F4): whether phone alerts can actually be delivered.
            "notification_service": service or None,
            "notification_service_found": (
                self.hass.services.has_service("notify", service) if service else None
            ),
        }

    async def async_turn_on(self, **kwargs):
        await self.runtime.executor.async_set_enabled(True)

    async def async_turn_off(self, **kwargs):
        await self.runtime.executor.async_set_enabled(False)
