"""Editable entity mapping and explicit unverified assumptions; no cloud setup."""

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv, selector
import voluptuous as vol

from .config import (
    DEFAULT_OPTIONS,
    DEFAULT_SOURCES,
    OPTIONAL_SOURCES,
    DOMAIN,
    parse_options,
    rejection_message,
    saved_options,
)
from .settings import CATALOG, apply_changes, locked_changes, locked_message


def sources_schema(values):
    return vol.Schema(
        {
            vol.Required(key, default=values.get(key, default)): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="water_heater" if key == "heater" else "sensor"
                )
            )
            for key, default in DEFAULT_SOURCES.items()
        }
        | {
            vol.Optional(
                key, **({"default": values[key]} if values.get(key) else {})
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
            for key in OPTIONAL_SOURCES
        }
    )


PAGES = {
    # Configure menu page -> setting groups shown on it (retired settings are
    # never shown; their stored values are kept).
    "preferences": ("Everyday", "Advanced"),
    "system": ("System",),
}


def options_schema(values, groups=("Everyday", "Advanced", "System")):
    fields = {}
    for key, default in DEFAULT_OPTIONS.items():
        if CATALOG[key].group not in groups:
            continue
        if type(default) is bool:
            validator = cv.boolean
        elif key in {"tariff_clock", "native_schedule_clock"}:
            validator = vol.In(["local", "standard"])
        elif key in {"tariff_periods", "native_schedule_periods"}:
            validator = selector.TextSelector(selector.TextSelectorConfig(multiline=True))
        elif key == "native_clock_check_date" or CATALOG[key].kind == "text":
            validator = cv.string
        elif CATALOG[key].kind == "select":
            validator = selector.SelectSelector(
                selector.SelectSelectorConfig(options=list(CATALOG[key].choices))
            )
        elif CATALOG[key].kind == "time":
            validator = selector.TimeSelector()
        else:
            low, high = CATALOG[key].low, CATALOG[key].high
            validator = vol.All(vol.Coerce(float), vol.Range(min=low, max=high))
        fields[vol.Required(key, default=values.get(key, default))] = validator
    return vol.Schema(fields)


class ShadowConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 3

    async def async_step_user(self, user_input=None):
        await self.async_set_unique_id("thermann_shadow_315l")
        self._abort_if_unique_id_configured()
        if user_input is not None:
            for entity in user_input.values():
                cv.entity_id(entity)
            return self.async_create_entry(title="Thermann Shadow", data=user_input)
        return self.async_show_form(step_id="user", data_schema=sources_schema(DEFAULT_SOURCES))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ShadowOptionsFlow(config_entry)


class ShadowOptionsFlow(config_entries.OptionsFlow):
    """Configure: a menu of three pages. Each page validates the COMPLETE
    resulting configuration and saves only that page's values."""

    def __init__(self, entry):
        self._entry = entry
        self._locked = ""

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init", menu_options=["preferences", "system", "sources"]
        )

    def _current_sources(self):
        return dict(self._entry.options.get("sources", self._entry.data))

    def _finish(self, before, result, step_id, schema):
        from .settings_entity import control_active

        locked = locked_changes(before, result)
        if locked and control_active(self.hass, self._entry):
            self._locked = locked_message(locked)
            return self.async_show_form(
                step_id=step_id,
                data_schema=schema,
                errors={"base": "locked_while_active"},
                description_placeholders={"detail": self._locked},
            )
        return self.async_create_entry(title="", data=result)

    async def async_step_sources(self, user_input=None):
        values = self._current_sources()
        if user_input is not None:
            for entity in user_input.values():
                cv.entity_id(entity)
            before = {**saved_options(self._entry.options), "sources": values}
            result = {**saved_options(self._entry.options), "sources": dict(user_input)}
            return self._finish(before, result, "sources", sources_schema(user_input))
        return self.async_show_form(step_id="sources", data_schema=sources_schema(values))

    async def async_step_preferences(self, user_input=None):
        return await self._settings_page("preferences", user_input)

    async def async_step_system(self, user_input=None):
        return await self._settings_page("system", user_input)

    async def _settings_page(self, step_id, user_input):
        groups = PAGES[step_id]
        values = saved_options(self._entry.options)
        errors = {}
        if user_input is not None:
            before = {**values, "sources": self._current_sources()}
            values = apply_changes(values, user_input)
            try:
                parse_options(values)
            except (ValueError, TypeError, KeyError, OverflowError) as error:
                errors["base"] = "invalid_settings"
                self._locked = rejection_message(error)
            else:
                result = {**values, "sources": self._current_sources()}
                return self._finish(before, result, step_id, options_schema(values, groups))
        return self.async_show_form(
            step_id=step_id,
            data_schema=options_schema(values, groups),
            errors=errors,
            description_placeholders={"detail": self._locked},
        )
