"""Thermann planner (0.4.0) plus the 0.5.0 production controller.

The planner never commands anything. The controller (executor.py/controller.py)
is the only component that may publish a Thermann mode command, and it cannot
do so until the owner completes commissioning and enables automatic control.
"""

from datetime import timedelta

from homeassistant.const import Platform
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .config import DOMAIN, LEGACY_MORNING_THRESHOLD_C, parse_options
from .executor import Executor
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
    Platform.DATETIME,
]


async def async_setup_entry(hass, entry):
    settings, tariffs = parse_options(entry.options)
    runtime = ShadowRuntime(hass, entry.options.get("sources", entry.data), settings, tariffs)
    runtime.set_native_reference(entry.options)
    executor = Executor(hass, entry, runtime)
    await executor.async_load()
    runtime.executor = executor
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    @callback
    def update(now):
        runtime.update(now)
        hass.async_create_task(executor.async_step(now))

    @callback
    def new_poll(event):
        # Evaluate immediately when a bridge status lands: a command sent then
        # needs no pre-command status read by the bridge (fewer cloud requests).
        update(dt_util.utcnow())

    entry.async_on_unload(async_track_time_interval(hass, update, timedelta(minutes=1)))
    poll_entity = runtime.sources.get("last_poll")
    if isinstance(poll_entity, str) and poll_entity:
        entry.async_on_unload(async_track_state_change_event(hass, [poll_entity], new_poll))
    entry.async_on_unload(entry.add_update_listener(_reload))
    update(dt_util.utcnow())
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
    runtime = hass.data[DOMAIN][entry.entry_id]
    runtime.apply_options(entry.options, entry.options.get("sources", entry.data))
    if runtime.executor is not None:
        runtime.executor.configure(entry.options)


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        return True
    return False
