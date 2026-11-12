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

import logging

from .config import DOMAIN, LEGACY_MORNING_THRESHOLD_C, migrate_0_7_1, parse_options
from .executor import Executor
from .naming import ENTRY_TITLE, OLD_ENTRY_TITLES
from .settings import RETIRED
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


# Entities no longer provided (unique-id suffixes after the entry id): the
# 0.3.0 simulation sensors, the 0.5.0 empty-Schedule confirmation and, since
# 0.8.0, the controls of retired settings. Their registry entries are removed so
# they do not linger as "unavailable"; stored option values are kept.
RETIRED_ENTITY_SUFFIXES = frozenset(
    {
        "simulated_cycle_count",
        "simulated_stop_count",
        "suppressed_switching_episodes",
        "simulated_cost_aud",
        "setting_controller_empty_schedule_confirmed",
        *(f"setting_{key}" for key in RETIRED),
    }
)


def _remove_retired_entities(hass, entry) -> None:
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_"
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        unique_id = item.unique_id or ""
        if unique_id.startswith(prefix) and unique_id[len(prefix) :] in RETIRED_ENTITY_SUFFIXES:
            registry.async_remove(item.entity_id)


async def async_setup_entry(hass, entry):
    settings, tariffs = parse_options(entry.options)
    _remove_retired_entities(hass, entry)
    if entry.title in OLD_ENTRY_TITLES:
        # 0.8.0 display name; the domain, entry, entities and IDs are unchanged.
        hass.config_entries.async_update_entry(entry, title=ENTRY_TITLE)
    runtime = ShadowRuntime(hass, entry.options.get("sources", entry.data), settings, tariffs)
    runtime.set_native_reference(entry.options)
    executor = Executor(hass, entry, runtime)
    await executor.async_load()
    from homeassistant.helpers.storage import Store

    from .thermal import ThermalObserver

    runtime.thermal_store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.thermal")
    try:
        runtime.thermal = ThermalObserver.from_dict(await runtime.thermal_store.async_load())
    except Exception:  # noqa: BLE001 - diagnostics only; start empty
        runtime.thermal = ThermalObserver()
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
    1.2 -> 1.3 (0.7.1): values outside the tightened ranges are brought inside.

    Only the exact old default is moved; any value the owner chose is kept.
    Major version stays 1, so a 0.3.0 rollback can still load the entry.
    """
    if entry.version != 1 or entry.minor_version >= 3:
        return True
    options = dict(entry.options)
    if entry.minor_version < 2 and options.get("morning_threshold_c") == LEGACY_MORNING_THRESHOLD_C:
        options["morning_threshold_c"] = 42.0
    # 1.2 -> 1.3 (0.7.1, settings audit): values outside the tightened ranges
    # move to the nearest allowed value, and each is logged. A 0.7.0 rollback
    # still loads a 1.3 entry (same major version).
    options, changes = migrate_0_7_1(options)
    for key, (old, new) in changes.items():
        logging.getLogger(__name__).warning(
            "Setting %s was %s, outside the range allowed since 0.7.1; now %s.", key, old, new
        )
    hass.config_entries.async_update_entry(entry, options=options, minor_version=3)
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
