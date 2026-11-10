"""Native LOCAL preference controls sharing config-entry options with Configure."""

from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo

from .config import DEFAULT_OPTIONS, DOMAIN, parse_options, saved_options
from .settings import CATALOG, recommended_options


async def save(hass, entry, changes=None, restore=False):
    values = saved_options(entry.options)
    values = recommended_options(values) if restore else {**values, **changes}
    try:
        parse_options(values)
    except (ValueError, TypeError, KeyError, OverflowError):
        raise HomeAssistantError(
            "Invalid shadow preferences. Morning must be before noon, afternoon after noon; "
            "tariff times must increase without overlaps; T-Comfort reference must not exceed "
            "the expected native target. Check the displayed planning bounds. Nothing was saved."
        ) from None
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
        default = DEFAULT_OPTIONS[self.key]
        return {
            "recommended_and_original_default": default,
            "explanation": self.meta.explanation,
            "group": self.meta.group,
            "shadow_only": True,
            "execution_enabled": False,
            "bounds_are_planning_validation_not_manufacturer_command_limits": True,
        }

    async def write(self, value):
        await save(self.hass, self.entry, {self.key: value})


def setup_controls(hass, entry, async_add_entities, kind, entity_class):
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [entity_class(entry, runtime, key) for key, meta in CATALOG.items() if meta.kind == kind]
    )
