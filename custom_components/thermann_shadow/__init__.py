"""Thermann Controller 0.18.1: one coordinated policy (simple_policy.py) and the
production controller. The controller (executor.py/controller.py) is the only
component that may publish a Thermann mode command, and it cannot do so until
the owner completes commissioning and enables automatic control. With control
off, the same policy runs as a read-only shadow observation.
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

from .config import DOMAIN, RETIRED_OPTIONS, migrate_0_7_1, migrate_0_18_0, parse_options
from .executor import Executor
from .naming import ENTRY_TITLE, OLD_ENTRY_TITLES, RETIRED_SENSORS
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
    Platform.DATE,
]


# Entities no longer provided (unique-id suffixes after the entry id): the
# 0.3.0 simulation sensors, the 0.5.0 empty-Schedule confirmation and, since
# 0.8.0, the controls of retired settings. Their registry entries are removed so
# they do not linger as "unavailable"; stored option values are kept.
RETIRED_ENTITY_SUFFIXES = frozenset(
    {
        *RETIRED_SENSORS,  # 0.3.0 simulation and, since 0.9.0, the planner's sensors
        # 0.9.0: the holiday departure and return datetimes became date entities.
        "holiday_start",
        "holiday_return",
        *(f"setting_{key}" for key in RETIRED_OPTIONS),
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
    from .performance import MeasuredHistory

    legacy_history_store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.measured_history")
    runtime.history_store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.measured_history_v2")
    try:
        saved_history = await runtime.history_store.async_load()
        if saved_history is None:
            saved_history = await legacy_history_store.async_load()
        runtime.history = MeasuredHistory.from_dict(saved_history)
    except Exception:  # noqa: BLE001 - observations remain usable without learned history
        runtime.history = MeasuredHistory()
    runtime.history.configure(
        settings.tank_litres,
        settings.element_kw,
        entry.options.get("heater_meter_verification", ""),
    )
    try:
        runtime.thermal = ThermalObserver.from_dict(await runtime.thermal_store.async_load())
    except Exception:  # noqa: BLE001 - diagnostics only; start empty
        runtime.thermal = ThermalObserver()
    runtime.executor = executor
    # Separate bounded diagnostic log; never a command/permission authority.
    runtime.owner_event_store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.owner_events")
    try:
        from .report import event

        saved = await runtime.owner_event_store.async_load() or {}
        for item in saved.get("events", [])[-200:]:
            if isinstance(item, dict):
                runtime.owner_events.append(event(item))
    except Exception:  # noqa: BLE001 - diagnostic loss must not disrupt command guards
        logging.getLogger(__name__).warning("Owner diagnostic history unavailable; starting empty.")
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
        now = dt_util.utcnow()
        runtime.capture_input_report(event, now)
        update(now)

    entry.async_on_unload(async_track_time_interval(hass, update, timedelta(minutes=1)))
    runtime.input_unsubscribe = None

    @callback
    def unbind_inputs():
        if runtime.input_unsubscribe:
            runtime.input_unsubscribe()
            runtime.input_unsubscribe = None

    @callback
    def bind_inputs():
        unbind_inputs()
        entities = sorted(
            {
                entity
                for key in ("last_poll", "grid", "heater_power", "pv")
                if isinstance(entity := runtime.sources.get(key), str) and entity
            }
        )
        if entities:
            runtime.input_unsubscribe = async_track_state_change_event(hass, entities, new_poll)

    runtime.rebind_inputs = bind_inputs
    bind_inputs()
    entry.async_on_unload(unbind_inputs)
    entry.async_on_unload(entry.add_update_listener(_reload))
    update(dt_util.utcnow())
    return True


async def async_migrate_entry(hass, entry):
    """Versioned option migrations. Major version stays 1, so older releases can
    still load the entry for a rollback.

    1.2 -> 1.3 (0.7.1): values outside the tightened ranges are brought inside.
    1.3 -> 1.4: implicit household facts of pre-0.11 installations are preserved.
    1.5 -> 1.6 (0.18.0): retired settings move, unchanged, into the unread
    ``retired_options`` record (config.migrate_0_18_0).
    (1.1 -> 1.2 once adjusted a morning threshold; that setting is retired.)
    """
    if entry.version != 1 or entry.minor_version >= 6:
        return True
    log = logging.getLogger(__name__)
    options = dict(entry.options)
    options, changes = migrate_0_7_1(options) if entry.minor_version < 3 else (options, {})
    for key, (old, new) in changes.items():
        log.warning(
            "Setting %s was %s, outside the range allowed since 0.7.1; now %s.", key, old, new
        )
    from .installation import preserve_existing

    if entry.minor_version < 4:
        options = preserve_existing(options, getattr(entry, "data", {}))
    else:
        options = {
            "meter_verified": False,
            "tariff_verified": False,
            "import_positive": True,
            "tariff_clock": "local",
            "time_zone": "Australia/Hobart",
            **options,
        }
    options, moved, kept = migrate_0_18_0(options)
    if moved:
        log.info(
            "0.18.0: %d retired settings moved unchanged to retired_options: %s.",
            len(moved),
            ", ".join(moved),
        )
    retired = options.get("retired_options", {})
    if "polling_mode" in moved:
        # Decision D2: the controller no longer has its own polling choice.
        log.warning(
            "0.18.0: the controller's own polling choice '%s' is retired; the controller "
            "now follows the Thermann Hot Water app's polling option (Smart plans only "
            "when the app reports Smart, otherwise the app's fixed schedule).",
            retired.get("polling_mode"),
        )
    if kept is not None:
        log.warning(
            "0.18.0: the stored solar start headroom is %s kW, not the agreed 0.3 kW. It is "
            "kept so solar qualification does not change; confirm it with the owner.",
            kept,
        )
    hass.config_entries.async_update_entry(entry, options=options, minor_version=6)
    return True


async def _reload(hass, entry):
    runtime = hass.data[DOMAIN][entry.entry_id]
    runtime.apply_options(entry.options, entry.options.get("sources", entry.data))
    if runtime.executor is not None:
        runtime.executor.configure(entry.options)
        if getattr(runtime, "rebind_inputs", None):
            runtime.rebind_inputs()
        # 0.9.1: the commissioning requirements shown on the master switch follow
        # a settings change at once (they were stale until the next minute).
        runtime.executor._notify_listeners()


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        runtime = hass.data[DOMAIN][entry.entry_id]
        await runtime._save_history()
        hass.data[DOMAIN].pop(entry.entry_id)
        return True
    return False
