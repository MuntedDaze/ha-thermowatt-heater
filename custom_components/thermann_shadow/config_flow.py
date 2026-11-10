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
    saved_options,
)
from .settings import CATALOG


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


def options_schema(values):
    fields = {}
    for key, default in DEFAULT_OPTIONS.items():
        if type(default) is bool:
            validator = cv.boolean
        elif key in {"tariff_clock", "native_schedule_clock"}:
            validator = vol.In(["local", "standard"])
        elif key in {"tariff_periods", "native_schedule_periods"}:
            validator = selector.TextSelector(selector.TextSelectorConfig(multiline=True))
        elif key == "native_clock_check_date":
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
    def __init__(self, entry):
        self._entry = entry
        self._sources = None

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            self._sources = user_input
            return await self.async_step_settings()
        values = self._entry.options.get("sources", self._entry.data)
        return self.async_show_form(step_id="init", data_schema=sources_schema(values))

    async def async_step_settings(self, user_input=None):
        errors = {}
        values = saved_options(self._entry.options)
        if user_input is not None:
            values.update(user_input)
            try:
                parse_options(values)
            except (ValueError, TypeError, KeyError, OverflowError):
                errors["base"] = "invalid_settings"
            else:
                return self.async_create_entry(title="", data={**values, "sources": self._sources})
        return self.async_show_form(
            step_id="settings", data_schema=options_schema(values), errors=errors
        )
