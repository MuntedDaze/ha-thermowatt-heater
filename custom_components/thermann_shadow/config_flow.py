"""Editable entity mapping and explicit unverified assumptions; no cloud setup."""

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv, selector
import voluptuous as vol

from .config import DEFAULT_OPTIONS, DEFAULT_SOURCES, DOMAIN, parse_options


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
        else:
            ranges = {
                "target_c": (65, 70),
                "expected_native_target_c": (20, 75),
                "margin_minutes": (0, 120),
                "feed_in_rate": (0, 2),
                "export_headroom_kw": (0, 3),
                "status_max_age_minutes": (30, 90),
                "grid_max_age_seconds": (30, 300),
                "t_comfort_reference_c": (10, 75),
            }
            low, high = ranges.get(key, (-5, 10))
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
        values = {**DEFAULT_OPTIONS, **self._entry.options}
        if user_input is not None:
            values.update(user_input)
            try:
                parse_options(values)
            except (ValueError, TypeError, KeyError, OverflowError):
                errors["base"] = "invalid_settings"
            else:
                return self.async_create_entry(
                    title="", data={**user_input, "sources": self._sources}
                )
        return self.async_show_form(
            step_id="settings", data_schema=options_schema(values), errors=errors
        )
