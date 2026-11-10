"""Thermann shadow planning only; no services, network clients or heater writes."""

from datetime import timedelta

from homeassistant.const import Platform
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .config import DOMAIN, parse_options
from .runtime import ShadowRuntime

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass, entry):
    settings, tariffs = parse_options(entry.options)
    runtime = ShadowRuntime(hass, entry.options.get("sources", entry.data), settings, tariffs)
    runtime.set_native_reference(entry.options)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])

    @callback
    def update(now):
        runtime.update(now)

    entry.async_on_unload(async_track_time_interval(hass, update, timedelta(minutes=1)))
    entry.async_on_unload(entry.add_update_listener(_reload))
    runtime.update(dt_util.utcnow())
    return True


async def _reload(hass, entry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR]):
        hass.data[DOMAIN].pop(entry.entry_id)
        return True
    return False
