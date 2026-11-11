"""Restore or undo local recommendations only; dashboard asks for confirmation."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from .config import DOMAIN
from .settings import BACKUP_KEY, RESTORED
from .settings_entity import save


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            RestoreRecommendations(entry, runtime),
            UndoRestore(entry, runtime),
            ControllerAction(
                entry, runtime, "hold", "Hold heater (owner override)", "mdi:hand-back-left"
            ),
            ControllerAction(
                entry, runtime, "resume", "Resume automatic control", "mdi:play-circle"
            ),
            ControllerAction(
                entry, runtime, "acknowledge", "Acknowledge controller fault", "mdi:check-decagram"
            ),
        ]
    )


class _LocalButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(self, entry, runtime):
        self.entry, self.runtime = entry, runtime
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Thermann Shadow",
            manufacturer="Community shadow planner",
            model="315 L / 3 kW scenario",
        )

    async def async_added_to_hass(self):
        self.async_on_remove(self.runtime.subscribe(self.async_write_ha_state))


class RestoreRecommendations(_LocalButton):
    """Unique ID kept from the first 0.3.0 candidate."""

    _attr_name = "Restore recommended preferences"
    _attr_icon = "mdi:restore"

    def __init__(self, entry, runtime):
        super().__init__(entry, runtime)
        self._attr_unique_id = f"{entry.entry_id}_restore_recommended"

    @property
    def extra_state_attributes(self):
        return {
            "restores": list(RESTORED),
            "preserves": "mappings, verifications, meter direction, tariff contract, native references",
            "undo_available": isinstance(self.entry.options.get(BACKUP_KEY), dict),
            "heater_commands": 0,
        }

    async def async_press(self):
        await save(self.hass, self.entry, restore=True)


class UndoRestore(_LocalButton):
    _attr_name = "Undo last restore"
    _attr_icon = "mdi:undo-variant"

    def __init__(self, entry, runtime):
        super().__init__(entry, runtime)
        self._attr_unique_id = f"{entry.entry_id}_undo_restore"

    @property
    def available(self):
        return isinstance(self.entry.options.get(BACKUP_KEY), dict)

    async def async_press(self):
        await save(self.hass, self.entry, undo=True)


class ControllerAction(_LocalButton):
    """Owner override, resume and fault acknowledgement. None of these sends a
    heater command: resume/acknowledge only let the controller RE-INSPECT the
    heater from a new status before it may act again."""

    _attr_entity_category = None

    def __init__(self, entry, runtime, action, name, icon):
        super().__init__(entry, runtime)
        self.action = action
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_controller_{action}"

    async def async_press(self):
        from homeassistant.exceptions import HomeAssistantError

        if not await self.runtime.executor.async_owner_action(self.action):
            raise HomeAssistantError(f"Nothing to {self.action} in the current controller state.")
