"""Native LOCAL preference controls sharing config-entry options with Configure."""

from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo

from .config import DOMAIN, parse_options, rejection_message, saved_options
from .settings import (
    CATALOG,
    RETIRED,
    apply_changes,
    describe,
    locked_changes,
    locked_message,
    recommended_options,
    undo_restore,
)


def control_active(hass, entry) -> bool:
    """Whether automatic heater control is currently ON for this entry."""
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    executor = getattr(runtime, "executor", None)
    return bool(executor is not None and executor.controller.enabled)


async def save(hass, entry, changes=None, restore=False, undo=False):
    values = saved_options(entry.options)
    before = dict(values)
    if undo:
        try:
            values = undo_restore(values)
        except ValueError:
            raise HomeAssistantError("There is no restore to undo. Nothing was changed.") from None
    elif restore:
        values = recommended_options(values)
    else:
        values = apply_changes(values, changes)
    try:
        parse_options(values)
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise HomeAssistantError(f"{rejection_message(error)} Nothing was saved.") from None
    locked = locked_changes(before, values)
    if locked and control_active(hass, entry):
        raise HomeAssistantError(locked_message(locked))
    hass.config_entries.async_update_entry(entry, options=values)


class SettingEntity:
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry, runtime, key):
        self.entry, self.runtime, self.key = entry, runtime, key
        self.meta = CATALOG[key]
        self._attr_name = self.meta.name
        self._attr_unique_id = f"{entry.entry_id}_setting_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Thermann Shadow",
            manufacturer="Community shadow planner",
            model="315 L / 3 kW scenario",
        )

    async def async_added_to_hass(self):
        self.async_on_remove(self.runtime.subscribe(self.async_write_ha_state))

    @property
    def current(self):
        return saved_options(self.entry.options)[self.key]

    @property
    def extra_state_attributes(self):
        return {
            **describe(self.key, self.current),
            "explanation": self.meta.explanation,
            "group": self.meta.group,
            "shadow_only": not getattr(self.runtime, "controller_active", False),
            "execution_enabled": bool(getattr(self.runtime, "controller_active", False)),
            "bounds_are_planning_validation_not_manufacturer_command_limits": True,
        }

    async def write(self, value):
        await save(self.hass, self.entry, {self.key: value})


def setup_controls(hass, entry, async_add_entities, kind, entity_class):
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            entity_class(entry, runtime, key)
            for key, meta in CATALOG.items()
            if meta.kind == kind and key not in RETIRED
        ]
    )
