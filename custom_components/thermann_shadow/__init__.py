"""Thermann shadow planning only; no services, network clients or heater writes."""

from datetime import timedelta

from homeassistant.const import Platform
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .config import DOMAIN, LEGACY_MORNING_THRESHOLD_C, parse_options
from .runtime import ShadowRuntime

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.TIME,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.TEXT,
    Platform.BUTTON,
]


async def async_setup_entry(hass, entry):
    settings, tariffs = parse_options(entry.options)
    runtime = ShadowRuntime(hass, entry.options.get("sources", entry.data), settings, tariffs)
    runtime.set_native_reference(entry.options)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def update(now):
        runtime.update(now)

    entry.async_on_unload(async_track_time_interval(hass, update, timedelta(minutes=1)))
    entry.async_on_unload(entry.add_update_listener(_reload))
    runtime.update(dt_util.utcnow())
    return True


async def async_migrate_entry(hass, entry):
    """1.1 -> 1.2 (0.4.0): an untouched old 40 °C morning threshold becomes 42 °C.

    Only the exact old default is moved; any value the owner chose is kept.
    Major version stays 1, so a 0.3.0 rollback can still load the entry.
    """
    if entry.version == 1 and entry.minor_version < 2:
        options = dict(entry.options)
        if options.get("morning_threshold_c") == LEGACY_MORNING_THRESHOLD_C:
            options["morning_threshold_c"] = 42.0
        hass.config_entries.async_update_entry(entry, options=options, minor_version=2)
    return True


async def _reload(hass, entry):
    hass.data[DOMAIN][entry.entry_id].apply_options(
        entry.options, entry.options.get("sources", entry.data)
    )


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        return True
    return False
