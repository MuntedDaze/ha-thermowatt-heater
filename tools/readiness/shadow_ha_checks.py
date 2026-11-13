"""Phase 2B checks for shadow_ha_smoke.py. Runs ONLY inside an isolated HA Core
container with --network none. Never import this on the owner's Home Assistant.

- every native settings entity, driven through the REAL HA service layer;
- invalid combinations, atomic saves, restore and undo;
- every dashboard entity reference and every markdown template rendered by HA;
- forecast-present, Forecast.Solar, flat-baseline and invalid/stale paths;
- genuine 0.2.0, 0.3.0, 0.5.0, 0.6.0, 0.6.1, 0.6.2 and 0.7.0 -> 0.7.1 upgrades over persisted HA storage;
- unchanged MQTT payloads (no state write) stay fresh while polls succeed.
"""

from datetime import timedelta
import json
from pathlib import Path
import re
import shutil
import sys

import yaml

from homeassistant import bootstrap, config_entries, loader
from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE
from homeassistant.core import HomeAssistant, ServiceRegistry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.template import Template
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import METRIC_SYSTEM

ROOT = Path("/workspace")
CURRENT_VERSION = "0.9.1"
LEGACY = ROOT / "tools/readiness/fixtures/thermann_shadow_0_2_0"
SETTING_DOMAINS = {"number", "time", "select", "switch", "text", "button"}
NATIVE_CARDS = {
    "markdown",
    "tile",
    "gauge",
    "heading",
    "entities",
    "history-graph",
    "button",
    "grid",
}
ALERT_TYPES = {"info", "warning", "error", "success"}

# Service calls are denied unless the TEST DRIVER makes them, and then only to
# this integration's local settings entities. The integration itself never calls.
DRIVER = {"active": False, "calls": 0}
_original_call = ServiceRegistry.async_call


async def _guarded_call(self, domain, service, service_data=None, *args, **kwargs):
    target = json.dumps([service_data, args, kwargs], default=str)
    if (
        not DRIVER["active"]
        or domain not in SETTING_DOMAINS
        or "thermann_shadow_" not in target
        or re.search(r"\b(?:water_heater|climate|mqtt)\.", target)
    ):
        raise AssertionError("Shadow integration attempted a service call")
    DRIVER["calls"] += 1
    return await _original_call(self, domain, service, service_data, *args, **kwargs)


def install_service_guard():
    ServiceRegistry.async_call = _guarded_call


async def drive(hass, domain, service, entity_id, **data):
    DRIVER["active"] = True
    try:
        await hass.services.async_call(
            domain, service, {"entity_id": entity_id, **data}, blocking=True
        )
    finally:
        DRIVER["active"] = False
    await hass.async_block_till_done()


async def start_hass(folder, component):
    """A fresh HA core over `folder`, with `component` as the custom integration."""
    for name in [name for name in sys.modules if name.split(".")[0] == "custom_components"]:
        del sys.modules[name]
    while folder in sys.path:
        sys.path.remove(folder)
    sys.path.insert(0, folder)
    target = Path(folder) / "custom_components/thermann_shadow"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(component, target)
    hass = HomeAssistant(folder)
    loader.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await hass.config_entries.async_initialize()
    assert await bootstrap.async_load_base_functionality(hass)
    await hass.config.async_set_time_zone("Australia/Hobart")
    hass.config.units = METRIC_SYSTEM
    assert await async_setup_component(hass, "sensor", {})
    return hass


async def flush_and_close(hass):
    """Unload entries, then persist storage the way a real shutdown does.

    hass.async_stop() is a no-op for a core that was never started, so fire the
    final-write event that every delayed Store (config entries, registries)
    listens for, and wait for the executor writes to finish.
    """
    for entry in hass.config_entries.async_entries("thermann_shadow"):
        if entry.state is config_entries.ConfigEntryState.LOADED:
            assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
    await hass.async_block_till_done()
    storage = Path(hass.config.config_dir) / ".storage"
    return {path.name for path in storage.iterdir()} if storage.exists() else set()


def report_inputs(hass, sources, temperature=55, grid=1501, pv=2322, house=821):
    now = dt_util.utcnow()
    values = {
        "heater": ("unknown", {"current_temperature": temperature, "temperature": 70}),
        "mode": ("Schedule", {}),
        "last_poll": (now.isoformat(), {}),
        "cloud_health": ("ok", {}),
        "requests": (4, {"accounting_complete": True, "accounting_persistent": True}),
        "grid": (grid, {"unit_of_measurement": "W"}),
        "pv": (pv, {"unit_of_measurement": "W"}),
        "house": (house, {"unit_of_measurement": "W"}),
        "import_energy": (1234, {"unit_of_measurement": "kWh"}),
        "export_energy": (5678, {"unit_of_measurement": "kWh"}),
    }
    for key, (state, attrs) in values.items():
        hass.states.async_set(sources[key], state, attrs, force_update=True)
    return now


# --- 0.2.0 -> 0.3.0 upgrade over persisted storage ---------------------------------


LEGACY_CUSTOM_TARIFF = json.dumps(
    [{"days": [0, 1, 2, 3, 4, 5, 6], "start": "00:00", "end": "00:00", "kind": "off_peak"}]
)


RETIRED_IN_0_4_0 = (
    "simulated_cycle_count",
    "simulated_stop_count",
    "suppressed_switching_episodes",
    "simulated_cost_aud",
)


def is_retired(entry_id, unique_id):
    """Entities the CURRENT integration no longer provides (registry entry removed)."""
    from custom_components.thermann_shadow import RETIRED_ENTITY_SUFFIXES

    return (unique_id or "").removeprefix(f"{entry_id}_") in RETIRED_ENTITY_SUFFIXES


def kept(entry_id, ids):
    return {key: value for key, value in ids.items() if not is_retired(entry_id, key)}


async def options_page(hass, entry, page, data):
    """0.8.0 Configure: a menu (preferences / system / sources), one page per save."""
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] == "menu", flow
    assert set(flow["menu_options"]) == {"preferences", "system", "sources"}, flow
    flow = await hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": page}
    )
    assert flow["type"] == "form" and flow["step_id"] == page, flow
    return await hass.config_entries.options.async_configure(flow["flow_id"], data)


def page_values(entry, groups):
    from custom_components.thermann_shadow.config import DEFAULT_OPTIONS
    from custom_components.thermann_shadow.settings import CATALOG

    return {
        key: entry.options.get(key, value)
        for key, value in DEFAULT_OPTIONS.items()
        if CATALOG[key].group in groups
    }


async def upgrade_from(folder, fixture, version, customise):
    """Install an older frozen component, save options + an entity rename to real
    HA storage, stop, then load the CURRENT component over the same storage."""
    hass = await start_hass(folder, fixture)
    integration = await loader.async_get_custom_components(hass)
    assert integration["thermann_shadow"].version.__str__() == version
    from custom_components.thermann_shadow.config import DEFAULT_OPTIONS, DEFAULT_SOURCES
    from custom_components.thermann_shadow.sensor import SENSORS as OLD_SENSORS

    result = await hass.config_entries.flow.async_init(
        "thermann_shadow", context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DEFAULT_SOURCES)
    assert result["type"] == "create_entry", result
    entry = result["result"]
    await hass.async_block_till_done()
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], DEFAULT_SOURCES)
    saved = await hass.config_entries.options.async_configure(
        flow["flow_id"], {**DEFAULT_OPTIONS, **customise}
    )
    assert saved["type"] == "create_entry", saved
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    registry.async_update_entity(
        "sensor.thermann_shadow_controller", new_entity_id="sensor.hot_water_shadow_controller"
    )
    before = {
        item.unique_id: item.entity_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert "sensor.hot_water_shadow_controller" in before.values()
    sensors_before = len(OLD_SENSORS)
    saved_options = dict(entry.options)
    assert saved_options["morning_threshold_c"] == 40.0  # old default, saved explicitly
    entry_id = entry.entry_id
    stored = await flush_and_close(hass)
    assert {"core.config_entries", "core.entity_registry"} <= stored, stored

    hass = await start_hass(folder, ROOT / "custom_components/thermann_shadow")
    integration = await loader.async_get_custom_components(hass)
    assert integration["thermann_shadow"].version.__str__() == CURRENT_VERSION
    (entry,) = hass.config_entries.async_entries("thermann_shadow")
    assert entry.entry_id == entry_id and dict(entry.options) == saved_options
    assert await async_setup_component(hass, "thermann_shadow", {})
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED, entry.state
    # The only rewrite is the documented 1.1 -> 1.2 migration of the untouched
    # old 40 °C default to the 42 °C requirement; everything else is kept
    # (the 1.2 -> 1.3 range check of 0.7.1 changes nothing in range).
    assert entry.minor_version == 3
    assert dict(entry.options) == {**saved_options, "morning_threshold_c": 42.0}
    runtime = hass.data["thermann_shadow"][entry.entry_id]
    for key, value in customise.items():
        if key in {"target_c", "margin_minutes"}:
            assert getattr(runtime.settings, key) == value, key
    registry = er.async_get(hass)
    after = {
        item.unique_id: item.entity_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    # Identities and renames kept; retired entities' registry entries removed.
    assert {key: after[key] for key in kept(entry_id, before)} == kept(entry_id, before)
    assert not [key for key in after if is_retired(entry_id, key)], after
    retired = {f"{entry_id}_{key}" for key in RETIRED_IN_0_4_0}
    for entity_id in after.values():
        assert hass.states.get(entity_id) is not None, entity_id
    report_inputs(hass, DEFAULT_SOURCES)
    runtime.update(dt_util.utcnow())
    controller = hass.states.get("sensor.hot_water_shadow_controller")
    assert controller.attributes["controller_active"] is False
    json.dumps(dict(controller.attributes), allow_nan=False)
    await flush_and_close(hass)
    return {
        "from": version,
        "legacy_sensors": sensors_before,
        "legacy_entities": len(before),
        "entities_after_upgrade": len(after),
        "retired_still_registered": len(retired & set(after)),
        "morning_threshold_migrated_40_to_42": True,
    }


async def upgrade_from_0_2_0(folder):
    result = await upgrade_from(
        folder,
        LEGACY,
        "0.2.0",
        {
            "target_c": 65.0,
            "margin_minutes": 45.0,
            "import_positive": False,
            "tariff_periods": LEGACY_CUSTOM_TARIFF,
        },
    )
    assert result["legacy_sensors"] == 35
    return result


async def upgrade_from_0_3_0(folder):
    result = await upgrade_from(
        folder, ROOT / "tools/readiness/fixtures/thermann_shadow_0_3_0", "0.3.0", {}
    )
    # 0.8.0: the retired 0.3.0 simulation sensors are removed from the registry.
    assert result["retired_still_registered"] == 0
    return result


# --- Native settings through the real service layer --------------------------------


def alternate(key, meta, default):
    """A valid non-default value for each setting, in isolation."""
    if meta.kind == "switch":
        return not default
    if meta.kind == "select":
        return next(choice for choice in meta.choices if choice != default)
    if meta.kind == "text":
        return {
            "controller_notify_service": "mobile_app_test",  # 0.7.1: name validated
            "controller_command_topic": "P/TEST999/CMD/MODE",
        }.get(key, "2026-10-05")
    if meta.kind == "time":
        hour, minute = int(default[:2]), int(default[3:5])
        later = {"peak_morning_start": -30, "peak_evening_end": 30}.get(key, 30)
        total = hour * 60 + minute + later
        if key == "morning_time":
            total = hour * 60 + minute - 15
        return f"{total // 60:02d}:{total % 60:02d}"
    step = 0.01 if meta.high - meta.low <= 2 or key.endswith("rate") else 1
    value = default + step
    return round(value if value <= meta.high else default - step, 6)


async def set_setting(hass, entity_id, kind, value):
    if kind == "number":
        await drive(hass, "number", "set_value", entity_id, value=value)
    elif kind == "time":
        await drive(hass, "time", "set_value", entity_id, time=f"{value}:00")
    elif kind == "select":
        await drive(hass, "select", "select_option", entity_id, option=value)
    elif kind == "switch":
        await drive(hass, "switch", "turn_on" if value else "turn_off", entity_id)
    elif kind == "text":
        await drive(hass, "text", "set_value", entity_id, value=value)


def expected_state(kind, value):
    if kind == "switch":
        return "on" if value else "off"
    if kind == "time":
        return f"{value}:00"
    return str(value)


async def rejected(hass, entry, coroutine):
    before = dict(entry.options)
    try:
        await coroutine
    except (HomeAssistantError, ValueError):
        pass
    else:
        raise AssertionError("Invalid shadow preference accepted")
    finally:
        DRIVER["active"] = False
    assert dict(entry.options) == before, "rejected change modified options"


async def check_settings_services(hass, entry, runtime, entity_for):
    from custom_components.thermann_shadow.config import DEFAULT_OPTIONS
    from custom_components.thermann_shadow.settings import BACKUP_KEY, CATALOG, RESTORED

    checked = 0
    for key, meta in CATALOG.items():
        if meta.kind == "form" or meta.group == "Retired":
            continue
        entity_id = entity_for(key)
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        attrs = state.attributes
        assert attrs["recommended_default"] == DEFAULT_OPTIONS[key], key
        from custom_components.thermann_shadow.settings import ORIGINAL_DEFAULTS

        assert attrs["original_default"] == ORIGINAL_DEFAULTS[key], key
        assert attrs["explanation"] and attrs["group"] == meta.group
        assert attrs["execution_enabled"] is False
        current = entry.options.get(key, DEFAULT_OPTIONS[key])
        value = alternate(key, meta, current)
        await set_setting(hass, entity_id, meta.kind, value)
        stored = entry.options[key]
        assert stored == value or (meta.kind == "number" and float(stored) == value), (key, stored)
        state = hass.states.get(entity_id)
        if meta.kind == "number":
            assert abs(float(state.state) - value) < 1e-9, (key, state.state)
        else:
            assert state.state == expected_state(meta.kind, value), (key, state.state)
        assert state.attributes["current_value"] == stored
        assert state.attributes["changed_from_recommended"] is True
        assert runtime is hass.data["thermann_shadow"][entry.entry_id]  # no reload
        await set_setting(hass, entity_id, meta.kind, current)
        assert entry.options[key] == current or float(entry.options[key]) == current
        checked += 1
    # Cross-field and range validation through services: atomic, nothing saved.
    invalid = [
        ("time", "set_value", entity_for("peak_morning_end"), {"time": "17:00:00"}),
        # 0.7.1 (settings audit): readable cross-field and format rejections.
        ("text", "set_value", entity_for("controller_notify_service"), {"value": "notify.x"}),
    ]
    for domain, service, entity_id, data in invalid:
        await rejected(hass, entry, drive(hass, domain, service, entity_id, **data))
    # Restore and undo, through confirmed-dashboard button services.
    await set_setting(hass, entity_for("forecast_uncertainty"), "number", 0.3)
    await set_setting(hass, entity_for("peak_rate"), "number", 0.4)
    await set_setting(hass, entity_for("forecast_enabled"), "switch", True)
    await drive(hass, "button", "press", "button.thermann_shadow_restore_recommended_preferences")
    assert entry.options["forecast_uncertainty"] == 0.25
    # 0.9.1: the forecast switch is a commissioning requirement, not a
    # preference; a restore never turns the EMHASS forecasts off.
    assert entry.options["forecast_enabled"] is True
    assert entry.options["peak_rate"] == 0.4  # tariff contract preserved
    assert entry.options[BACKUP_KEY] == {"forecast_uncertainty": 0.3}
    assert runtime.settings.forecast_uncertainty == 0.25
    assert hass.states.get("button.thermann_shadow_undo_last_restore").state != "unavailable"
    await drive(hass, "button", "press", "button.thermann_shadow_undo_last_restore")
    assert entry.options["forecast_uncertainty"] == 0.3
    assert entry.options["forecast_enabled"] is True
    assert BACKUP_KEY not in entry.options and runtime.settings.forecast_uncertainty == 0.3
    assert hass.states.get("button.thermann_shadow_undo_last_restore").state == "unavailable"
    assert set(RESTORED) & {"peak_rate", "meter_verified", "import_positive"} == set()
    await drive(hass, "button", "press", "button.thermann_shadow_restore_recommended_preferences")
    await set_setting(hass, entity_for("peak_rate"), "number", DEFAULT_OPTIONS["peak_rate"])
    await set_setting(hass, entity_for("forecast_enabled"), "switch", False)
    return checked


# --- Dashboard: references, card types and rendered templates ----------------------


def dashboard_contract():
    dashboard = yaml.safe_load((ROOT / "shadow_controller/dashboard.yaml").read_text("utf-8"))
    text = json.dumps(dashboard)
    refs = sorted(
        set(
            re.findall(
                r"\b(?:sensor|number|time|select|switch|text|button)\.thermann_shadow_[a-z0-9_]+",
                text,
            )
        )
    )
    cards, templates = [], []

    def walk(node):
        if isinstance(node, dict):
            if "type" in node and (
                "entity" in node
                or "content" in node
                or "cards" in node
                or "entities" in node
                or "heading" in node
            ):
                cards.append(node["type"])
            if node.get("type") == "markdown":
                templates.append(node["content"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(dashboard)
    return dashboard, refs, cards, templates


def validate_dashboard(hass, label):
    dashboard, refs, cards, templates = dashboard_contract()
    missing = [ref for ref in refs if hass.states.get(ref) is None]
    assert not missing, (label, missing)
    assert set(cards) <= NATIVE_CARDS, set(cards) - NATIVE_CARDS
    assert dashboard["views"][0]["type"] == "sections"
    for content in templates:
        info = Template(content, hass).async_render_to_info()
        assert info.exception is None, (label, info.exception, content[:80])
        rendered = info.result()
        assert "Traceback" not in rendered and "TemplateError" not in rendered
        for kind in re.findall(r'alert-type="([^"]*)"', rendered):
            assert kind in ALERT_TYPES, (label, kind)
    return len(refs), len(templates)


# --- Forecast paths on real HA states ---------------------------------------------


def emhass_state(hass, entity_id, key, value, generated, unit="W"):
    start = dt_util.utcnow().replace(second=0, microsecond=0)
    rows = [
        {"date": (start + timedelta(minutes=30 * i)).isoformat(), key: str(value)}
        for i in range(48)
    ]
    hass.states.async_set(
        entity_id,
        str(value),
        {"unit_of_measurement": unit, "forecasts": rows, "forecast_generated_at": generated},
        force_update=True,
    )


async def check_forecasts(hass, entry, entity_for):
    from custom_components.thermann_shadow.config import DEFAULT_SOURCES

    pv_id, load_id = "sensor.thermann_test_pv_forecast", "sensor.thermann_test_load_forecast"
    now = dt_util.utcnow().isoformat()
    emhass_state(hass, pv_id, "p_pv_forecast", 4500, now)
    emhass_state(hass, load_id, "p_load_forecast", 600, now)
    mapping = {**DEFAULT_SOURCES, "forecast_pv": pv_id, "forecast_load": load_id}
    saved = await options_page(hass, entry, "sources", mapping)
    assert saved["type"] == "create_entry", saved
    await hass.async_block_till_done()
    values = page_values(entry, ("Everyday", "Advanced"))
    saved = await options_page(hass, entry, "preferences", {**values, "forecast_enabled": True})
    assert saved["type"] == "create_entry", saved
    await hass.async_block_till_done()
    runtime = hass.data["thermann_shadow"][entry.entry_id]
    assert runtime.sources["forecast_pv"] == pv_id and runtime.settings.forecast_enabled
    # Mapping change resets freshness: generation must be after the new start.
    generated = dt_util.utcnow().isoformat()
    emhass_state(hass, pv_id, "p_pv_forecast", 4500, generated)
    emhass_state(hass, load_id, "p_load_forecast", 600, generated)
    # 30°C needs heat for either goal (40°C morning or 65-70°C afternoon), so the
    # fallback reservation exists whatever time of day CI runs.
    report_inputs(hass, DEFAULT_SOURCES, temperature=30, grid=3000, pv=4500)
    runtime.update(dt_util.utcnow())
    results = {}
    assert runtime.forecast.source == "published_pv_and_house_load", runtime.forecast.warnings
    assert runtime.forecast.load_basis == "published_household_load_forecast"
    assert runtime.details["forecast"]["intervals"] > 0
    surplus = hass.states.get("sensor.thermann_shadow_forecast_net_surplus")
    # 0.9.0: the forecast NET export now (EMHASS PV minus household load, with the
    # configured uncertainty margins), which the policy prices slot by slot.
    assert 0 < float(surplus.state) <= 4.5, surplus.state
    assert float(hass.states.get("sensor.thermann_shadow_forecast_age").state) < 5
    results["emhass"] = runtime.values.get("decision")
    validate_dashboard(hass, "forecast_present")
    # Forecast.Solar trigger-template buffer shape plus a Statistics-style baseline.
    start = dt_util.as_local(dt_util.utcnow()).replace(minute=0, second=0, microsecond=0)
    watts = {(start + timedelta(hours=h)).isoformat(): 3800 for h in range(12)}
    hass.states.async_set(
        pv_id,
        "12",
        {"unit_of_measurement": "W", "watts": watts, "forecast_generated_at": generated},
        force_update=True,
    )
    hass.states.async_set(load_id, "700", {"unit_of_measurement": "W"}, force_update=True)
    runtime.update(dt_util.utcnow())
    assert runtime.forecast.source == "published_pv_and_house_load", runtime.forecast.warnings
    assert runtime.forecast.load_basis == "flat_measured_household_baseline"
    results["forecast_solar_flat_load"] = runtime.values.get("decision")
    # Stale generation, invalid units and missing entities fall back safely.
    stale = (dt_util.utcnow() - timedelta(hours=3)).isoformat()
    for label, change in (
        ("stale", lambda: emhass_state(hass, pv_id, "p_pv_forecast", 4500, stale)),
        ("unit", lambda: emhass_state(hass, pv_id, "p_pv_forecast", 4500, generated, "kWh")),
        ("missing", lambda: hass.states.async_remove(pv_id)),
    ):
        change()
        emhass_state(hass, load_id, "p_load_forecast", 600, generated)
        runtime.update(dt_util.utcnow())
        assert runtime.forecast.source == "unavailable", label
        assert not runtime.forecast.slots, label
        assert runtime.values["forecast_net_surplus_kw"] is None
        results[label] = runtime.forecast.source
        validate_dashboard(hass, f"forecast_{label}")
    # Switch back off through the settings entity; mappings stay saved.
    await set_setting(hass, entity_for("forecast_enabled"), "switch", False)
    assert entry.options["sources"]["forecast_pv"] == pv_id
    assert runtime.forecast.source == "disabled"
    return results


async def check_unchanged_mqtt_payload_freshness(hass, entry):
    """Stage 1 F1 regression on real HA: cloud entities NOT rewritten for 50 min
    (identical MQTT payloads cause no state write) while the bridge keeps polling."""
    from custom_components.thermann_shadow.config import DEFAULT_SOURCES

    runtime = hass.data["thermann_shadow"][entry.entry_id]
    now = dt_util.utcnow()
    old = (now - timedelta(minutes=50)).timestamp()
    values = {
        "heater": ("unknown", {"current_temperature": 55, "temperature": 70}),
        "mode": ("Schedule", {"Cmd": 17, "WaterHeaterSts": 32}),
        "cloud_health": ("ok", {}),
    }
    for key, (state, attrs) in values.items():
        hass.states.async_set(DEFAULT_SOURCES[key], state, attrs, timestamp=old)
    assert hass.states.get(DEFAULT_SOURCES["mode"]).last_reported.timestamp() == old
    hass.states.async_set(DEFAULT_SOURCES["last_poll"], (now - timedelta(minutes=5)).isoformat())
    for key, value in {"grid": 1501, "pv": 2322, "house": 821}.items():
        hass.states.async_set(DEFAULT_SOURCES[key], value, {"unit_of_measurement": "W"})
    now = dt_util.utcnow()  # after the meter writes, so they are not "from the future"
    runtime.update(now)
    assert runtime.values["temperature"] == 55
    assert runtime.details["status_fresh"] is True
    # A genuinely old poll is not used.
    hass.states.async_set(DEFAULT_SOURCES["last_poll"], (now - timedelta(minutes=50)).isoformat())
    runtime.update(now)
    assert runtime.values["temperature"] is None
    assert runtime.details["status_fresh"] is False
    hass.states.async_set(DEFAULT_SOURCES["last_poll"], (now - timedelta(minutes=5)).isoformat())
    runtime.update(now)
    return {"cloud_entities_last_written_minutes_ago": 50, "reading_available": True}


async def check_controller(hass, entry, entity_for):
    """Production controller (0.9.0: OFF / Manual 45 / Manual 70) on REAL HA Core.

    Fresh install refuses to enable; after commissioning, one poll produces
    exactly one guarded MQTT message (captured here, never sent: the network is
    off and the MQTT helper is replaced by a recorder); repeated evaluations do
    not duplicate it; observed Manual confirms it; state survives a reload;
    disabling sends nothing. The heater-command count in the summary stays 0.
    """
    from homeassistant.components import mqtt
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.thermann_shadow import simple_policy as sp
    from custom_components.thermann_shadow.config import DEFAULT_SOURCES
    from custom_components.thermann_shadow.settings import CATALOG

    master = "switch.thermann_shadow_automatic_heater_control"
    status = "sensor.thermann_shadow_automatic_control_state"
    captured = []
    original = getattr(mqtt, "async_publish", None)

    async def record(_hass, topic, payload, qos=0, retain=False, *args, **kwargs):
        captured.append((topic, payload, qos, retain))

    def bridge(mode, poll, temperature=50, total=200, setpoint=70):
        cmd = {"Off": 8, "Manual": 9}[mode]  # T3: the heater reports OFF as Cmd 8
        hass.states.async_set(
            DEFAULT_SOURCES["heater"],
            "off" if mode == "Off" else "performance",
            {"current_temperature": temperature, "temperature": setpoint},
        )
        hass.states.async_set(DEFAULT_SOURCES["mode"], mode, {"Cmd": cmd, "WaterHeaterSts": 32})
        hass.states.async_set(
            DEFAULT_SOURCES["cloud_health"],
            "ok",
            {
                "auth_guard_mode": "authorized",
                "consecutive_failures": 0,
                "cooldown_remaining_seconds": 0,
                "commands_enabled": True,
                "command_policy": "automation",
                "last_command": None,
                "command_status_refreshes_24h": 0,  # bridge 1.3.10
                "command_status_refresh_limit_24h": 24,
                "command_confirmation_followups_seconds": [60, 300],  # bridge 1.3.11
                "command_confirmation_pending": False,
                "command_transitions": [  # bridge 1.3.13
                    "Manual:45@70",
                    "Manual:45@off",
                    "Manual:70@45",
                    "Manual:70@off",
                    "off@45",
                    "off@70",
                ],
                "poll_interval_seconds": 1800,
            },
        )
        hass.states.async_set(
            DEFAULT_SOURCES["requests"],
            total,
            {"accounting_complete": True, "accounting_persistent": True},
        )
        hass.states.async_set(DEFAULT_SOURCES["last_poll"], poll.isoformat())

    mqtt.async_publish = record
    try:
        state = hass.states.get(master)
        assert state.state == "off", state
        # Command topic, three-state qualification and (0.9.1) published forecasts.
        assert len(state.attributes["commissioning_missing"]) == 3
        # Stage A (disabled): repeated evaluations neither publish, notify nor
        # rewrite the controller's storage file when nothing changed.
        idle = hass.data["thermann_shadow"][entry.entry_id].executor
        writes = []
        real_save = idle.store.async_save

        async def counting_save(data):
            writes.append(1)
            await real_save(data)

        idle.store.async_save = counting_save
        await idle.async_step()
        before = len(writes)
        for _ in range(5):
            await idle.async_step()
        assert len(writes) == before, "idle controller rewrote its storage"
        assert not captured
        idle.store.async_save = real_save
        try:
            await drive(hass, "switch", "turn_on", master)
        except HomeAssistantError:
            pass
        else:
            raise AssertionError("an uncommissioned controller was enabled")
        assert hass.states.get(master).state == "off"
        for key, value in (
            ("controller_command_topic", "P/TEST123/CMD/MODE"),
            ("controller_three_state_qualified", True),
        ):
            await set_setting(hass, entity_for(key), CATALOG[key].kind, value)
        # 0.9.1: still refused until the published forecasts are enabled.
        try:
            await drive(hass, "switch", "turn_on", master)
        except HomeAssistantError:
            pass
        else:
            raise AssertionError("automatic control was enabled without published forecasts")
        # The switch shows the remaining requirement at once (0.9.1: a settings
        # change refreshes it; before, it was stale until the next minute).
        await hass.async_block_till_done()
        assert hass.states.get(master).attributes["commissioning_missing"] == [
            "published_forecasts_not_enabled"
        ]
        await set_setting(hass, entity_for("forecast_enabled"), "switch", True)
        await drive(hass, "switch", "turn_on", master)
        assert hass.states.get(master).state == "on"
        # 0.7.1 (audit F1): with control ON, settings that decide where
        # commands go, whether they may be sent or what a price or measurement
        # means are refused through the real service path; preferences,
        # notifications and Restore recommended still apply at once.
        for key, value in (
            ("controller_command_topic", "P/OTHER99/CMD/MODE"),
            ("controller_three_state_qualified", False),
            ("controller_max_commands_per_day", 8),
            ("forecast_enabled", False),
            ("import_positive", True),
            ("peak_rate", 0.40),
        ):
            await rejected(
                hass, entry, set_setting(hass, entity_for(key), CATALOG[key].kind, value)
            )
        await set_setting(hass, entity_for("forecast_uncertainty"), "number", 0.3)
        assert hass.data["thermann_shadow"][entry.entry_id].settings.forecast_uncertainty == 0.3
        await set_setting(hass, entity_for("controller_notify_service"), "text", "mobile_app_x")
        await drive(
            hass, "button", "press", "button.thermann_shadow_restore_recommended_preferences"
        )
        assert entry.options["forecast_uncertainty"] == 0.25
        assert entry.options["controller_command_topic"] == "P/TEST123/CMD/MODE"
        await set_setting(hass, entity_for("controller_notify_service"), "text", "")
        executor = hass.data["thermann_shadow"][entry.entry_id].executor
        wanted = sp.Decision("storage", "real_ha_wiring_check", 5)
        executor.decide = lambda now, obs: (wanted, executor.controller.heater)
        hass.config.components.add("mqtt")
        # Parked OFF (Cmd 8) keeping 70, as observed in T3: the guarded transition goes.
        bridge("Off", dt_util.utcnow(), setpoint=70)
        await hass.async_block_till_done()
        commands = [item for item in captured if item[0].endswith("/CMD/MODE")]
        assert commands == [("P/TEST123/CMD/MODE", "Manual:70@off", 1, False)], captured
        # Activation also asked the bridge for ONE guarded status read.
        assert ("P/TEST123/refresh", "refresh", 0, False) in captured, captured
        assert hass.states.get(status).state == "confirming"
        for _ in range(5):
            await executor.async_step()
        commands = [item for item in captured if item[0].endswith("/CMD/MODE")]
        assert len(commands) == 1, "duplicate command"
        bridge("Manual", dt_util.utcnow(), total=202)
        await hass.async_block_till_done()
        assert hass.states.get(status).state == "storage_70"
        assert hass.states.get("sensor.thermann_shadow_last_command_result").state == "confirmed"
        assert hass.states.get("sensor.thermann_shadow_commands_in_last_24_hours").state == "1"
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get(master).state == "on"  # persisted with controller state
        assert hass.states.get(status).state == "observing"  # never assumed after restart
        commands = [item for item in captured if item[0].endswith("/CMD/MODE")]
        assert len(commands) == 1
        await drive(hass, "switch", "turn_off", master)
        assert hass.states.get(status).state == "disabled"
        bridge("Off", dt_util.utcnow(), total=204)
        await hass.async_block_till_done()
        commands = [item for item in captured if item[0].endswith("/CMD/MODE")]
        assert len(commands) == 1, "a disabled controller published"
        for key, value in (
            ("controller_command_topic", ""),
            ("controller_three_state_qualified", False),
            ("forecast_enabled", False),
        ):
            await set_setting(hass, entity_for(key), CATALOG[key].kind, value)
    finally:
        if "mqtt" in hass.config.components:
            hass.config.components.remove("mqtt")
        if original is not None:
            mqtt.async_publish = original
    return {
        "fresh_install_refused_enable": True,
        "guarded_messages_captured_not_sent": len(
            [item for item in captured if item[0].endswith("/CMD/MODE")]
        ),
        "duplicates": 0,
        "confirmed_from_observed_manual": True,
        "reinspects_after_reload": True,
        "disabled_sends_nothing": True,
    }


async def upgrade_from_0_6_0(folder):
    return await _upgrade_from_0_6(folder, "0.6.0")


async def upgrade_from_0_6_2(folder):
    """The owner's INSTALLED version since 12 Nov 2026 (0.6.2, control off;
    the installed files were compared and are identical to 5fe48e3)."""
    return await _upgrade_from_0_6(folder, "0.6.2")


async def upgrade_from_0_7_0(folder):
    """The owner's INSTALLED version since 12 Nov 2026 (0.7.0 build bbbc5f9,
    control off; the installed files were compared and are identical)."""
    return await _upgrade_from_0_6(folder, "0.7.0")


async def upgrade_from_0_6_1(folder):
    """Installed for T3b on 12 Nov 2026 (0.6.1, control off)."""
    return await _upgrade_from_0_6(folder, "0.6.1")


async def _upgrade_from_0_6(folder, version):
    """An installed 0.6.x (automatic control off) -> current.

    Saved options, an entity rename, every entity ID and the persisted DISABLED
    controller state survive unchanged; no option is added, removed or
    migrated; nothing is published."""
    from homeassistant.components import mqtt

    fixture = f"tools/readiness/fixtures/thermann_shadow_{version.replace('.', '_')}"
    hass = await start_hass(folder, ROOT / fixture)
    integration = await loader.async_get_custom_components(hass)
    assert integration["thermann_shadow"].version.__str__() == version
    from custom_components.thermann_shadow.config import DEFAULT_OPTIONS, DEFAULT_SOURCES

    result = await hass.config_entries.flow.async_init(
        "thermann_shadow", context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DEFAULT_SOURCES)
    entry = result["result"]
    await hass.async_block_till_done()
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], DEFAULT_SOURCES)
    customise = {"target_c": 68.0, "controller_max_commands_per_day": 5.0}
    old_options = {**DEFAULT_OPTIONS, **customise}
    old_options.pop("controller_three_state_qualified", None)  # new in 0.9.0
    saved = await hass.config_entries.options.async_configure(flow["flow_id"], old_options)
    assert saved["type"] == "create_entry", saved
    await hass.async_block_till_done()
    runtime = hass.data["thermann_shadow"][entry.entry_id]
    await runtime.executor.async_step()  # writes the 0.6.x controller state file
    assert runtime.executor.controller.state == "disabled"
    registry = er.async_get(hass)
    registry.async_update_entity(
        "sensor.thermann_shadow_controller", new_entity_id="sensor.hot_water_shadow_controller"
    )
    before = {
        item.unique_id: item.entity_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    saved_options, entry_id = dict(entry.options), entry.entry_id
    stored = await flush_and_close(hass)
    assert f"thermann_shadow.{entry_id}.controller" in stored, stored

    hass = await start_hass(folder, ROOT / "custom_components/thermann_shadow")
    integration = await loader.async_get_custom_components(hass)
    assert integration["thermann_shadow"].version.__str__() == CURRENT_VERSION
    captured = []

    async def record(*args, **kwargs):
        captured.append(args)

    original = getattr(mqtt, "async_publish", None)
    mqtt.async_publish = record
    try:
        (entry,) = hass.config_entries.async_entries("thermann_shadow")
        assert await async_setup_component(hass, "thermann_shadow", {})
        await hass.async_block_till_done()
        assert entry.state is config_entries.ConfigEntryState.LOADED, entry.state
        assert dict(entry.options) == saved_options  # nothing rewritten (all in range)
        assert entry.minor_version == 3  # 0.7.1 range check ran and changed nothing
        runtime = hass.data["thermann_shadow"][entry.entry_id]
        assert runtime.settings.target_c == 68.0
        assert runtime.executor.cfg.max_commands_per_day == 5
        assert runtime.executor.controller.enabled is False
        # 0.8.0 display names: entry and device renamed in place; the domain,
        # device identity and every entity ID stay (12hr Override keeps the
        # guest-mode IDs automations may use).
        from homeassistant.helpers import device_registry as dr

        assert entry.title == "Thermann Controller", entry.title
        (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        assert ("thermann_shadow", entry.entry_id) in device.identifiers, device
        assert device.name == "Thermann Controller", device
        assert "Unofficial" in device.manufacturer, device.manufacturer
        if version == "0.7.0":
            override = hass.states.get("button.thermann_shadow_start_guest_mode_12_h")
            assert override.attributes["friendly_name"] == "Thermann Controller Start 12hr Override"
            ends = hass.states.get("sensor.thermann_shadow_guest_mode_ends")
            assert ends.attributes["friendly_name"] == "Thermann Controller 12hr Override ends"
        after = {
            item.unique_id: item.entity_id
            for item in er.async_entries_for_config_entry(registry_of(hass), entry.entry_id)
        }
        # IDs and renames kept; retired entities' registry entries removed.
        assert {key: after[key] for key in kept(entry.entry_id, before)} == kept(
            entry.entry_id, before
        )
        assert not [key for key in after if is_retired(entry.entry_id, key)], after
        added = {key.removeprefix(f"{entry.entry_id}_") for key in set(after) - set(before)}
        assert added <= ADDED_IN_0_7_0 | ADDED_IN_0_9_0, added
        for unique_id, entity_id in after.items():
            if not unique_id.endswith(RETIRED_SUFFIXES):
                assert hass.states.get(entity_id) is not None, entity_id
        report_inputs(hass, DEFAULT_SOURCES)
        runtime.update(dt_util.utcnow())
        await runtime.executor.async_step()
        await hass.async_block_till_done()
        assert hass.states.get("switch.thermann_shadow_automatic_heater_control").state == "off"
        assert hass.states.get("sensor.thermann_shadow_automatic_control_state").state == "disabled"
        missing = hass.states.get("switch.thermann_shadow_automatic_heater_control").attributes[
            "commissioning_missing"
        ]
        assert missing == [
            "command_topic_not_configured",
            "three_state_commands_not_qualified",
            "published_forecasts_not_enabled",
        ]
        assert captured == []
    finally:
        if original is not None:
            mqtt.async_publish = original
    await flush_and_close(hass)
    return {
        "from": version,
        "options_unchanged": True,
        "entities_kept": len(before),
        "controller_state_kept_disabled": True,
        "published": 0,
    }


async def upgrade_from_0_5_0(folder):
    """The owner's INSTALLED version (0.5.0, disabled) -> current over real storage.

    Saved options (including the removed 0.5.0 empty-Schedule key), an entity
    rename, every entity ID and the persisted DISABLED controller state survive;
    the removed setting's entity is only orphaned; nothing is published."""
    from homeassistant.components import mqtt

    hass = await start_hass(folder, ROOT / "tools/readiness/fixtures/thermann_shadow_0_5_0")
    integration = await loader.async_get_custom_components(hass)
    assert integration["thermann_shadow"].version.__str__() == "0.5.0"
    from custom_components.thermann_shadow.config import DEFAULT_OPTIONS, DEFAULT_SOURCES

    result = await hass.config_entries.flow.async_init(
        "thermann_shadow", context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DEFAULT_SOURCES)
    entry = result["result"]
    await hass.async_block_till_done()
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], DEFAULT_SOURCES)
    customise = {"target_c": 68.0, "controller_max_commands_per_day": 5.0}
    old_options = {**DEFAULT_OPTIONS, **customise}
    old_options.pop("controller_three_state_qualified", None)  # new in 0.9.0
    saved = await hass.config_entries.options.async_configure(flow["flow_id"], old_options)
    assert saved["type"] == "create_entry", saved
    await hass.async_block_till_done()
    assert "controller_empty_schedule_confirmed" in entry.options  # 0.5.0 key saved
    runtime = hass.data["thermann_shadow"][entry.entry_id]
    await runtime.executor.async_step()  # writes the 0.5.0 controller state file
    assert runtime.executor.controller.state == "disabled"
    registry = er.async_get(hass)
    registry.async_update_entity(
        "sensor.thermann_shadow_controller", new_entity_id="sensor.hot_water_shadow_controller"
    )
    before = {
        item.unique_id: item.entity_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    removed = f"{entry.entry_id}_setting_controller_empty_schedule_confirmed"
    assert removed in before
    saved_options, entry_id = dict(entry.options), entry.entry_id
    stored = await flush_and_close(hass)
    assert f"thermann_shadow.{entry_id}.controller" in stored, stored

    hass = await start_hass(folder, ROOT / "custom_components/thermann_shadow")
    integration = await loader.async_get_custom_components(hass)
    assert integration["thermann_shadow"].version.__str__() == CURRENT_VERSION
    captured = []

    async def record(*args, **kwargs):
        captured.append(args)

    original = getattr(mqtt, "async_publish", None)
    mqtt.async_publish = record
    try:
        (entry,) = hass.config_entries.async_entries("thermann_shadow")
        assert await async_setup_component(hass, "thermann_shadow", {})
        await hass.async_block_till_done()
        assert entry.state is config_entries.ConfigEntryState.LOADED, entry.state
        assert dict(entry.options) == saved_options  # nothing rewritten (all in range)
        assert entry.minor_version == 3  # 0.7.1 range check ran and changed nothing
        runtime = hass.data["thermann_shadow"][entry.entry_id]
        assert runtime.settings.target_c == 68.0
        assert runtime.executor.cfg.max_commands_per_day == 5
        assert runtime.executor.controller.enabled is False
        # 0.8.0 display names: entry and device renamed in place; the domain,
        # device identity and every entity ID stay (12hr Override keeps the
        # guest-mode IDs automations may use).
        from homeassistant.helpers import device_registry as dr

        assert entry.title == "Thermann Controller", entry.title
        (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
        assert ("thermann_shadow", entry.entry_id) in device.identifiers, device
        assert device.name == "Thermann Controller", device
        assert "Unofficial" in device.manufacturer, device.manufacturer
        after = {
            item.unique_id: item.entity_id
            for item in er.async_entries_for_config_entry(registry_of(hass), entry.entry_id)
        }
        # Identities and renames kept; retired entities' registry entries removed.
        assert {key: after[key] for key in kept(entry.entry_id, before)} == kept(
            entry.entry_id, before
        )
        assert not [key for key in after if is_retired(entry.entry_id, key)], after
        assert hass.states.get(before[removed]) is None  # orphaned, not provided
        for unique_id, entity_id in after.items():
            if unique_id != removed and unique_id in before:
                if not unique_id.endswith(RETIRED_SUFFIXES):
                    assert hass.states.get(entity_id) is not None, entity_id
        report_inputs(hass, DEFAULT_SOURCES)
        runtime.update(dt_util.utcnow())
        await runtime.executor.async_step()
        await hass.async_block_till_done()
        assert hass.states.get("switch.thermann_shadow_automatic_heater_control").state == "off"
        assert hass.states.get("sensor.thermann_shadow_automatic_control_state").state == "disabled"
        missing = hass.states.get("switch.thermann_shadow_automatic_heater_control").attributes[
            "commissioning_missing"
        ]
        assert missing == [
            "command_topic_not_configured",
            "three_state_commands_not_qualified",
            "published_forecasts_not_enabled",
        ]
        assert captured == []
    finally:
        if original is not None:
            mqtt.async_publish = original
    await flush_and_close(hass)
    return {
        "from": "0.5.0",
        "options_unchanged": True,
        "entities_kept": len(before) - 1,
        "removed_setting_orphaned": True,
        "controller_state_kept_disabled": True,
        "published": 0,
    }


def registry_of(hass):
    return er.async_get(hass)


RETIRED_SUFFIXES = tuple(f"_{key}" for key in RETIRED_IN_0_4_0)
# Entities new in 0.7.0 (unique-id suffixes after the entry id).
ADDED_IN_0_7_0 = {
    "setting_morning_preferred_time",
    "setting_morning_hard_time",
    "setting_morning_preferred_c",
    "controller_guest_start",
    "controller_guest_cancel",
    "controller_holiday_cancel",
    "holiday_start",
    "holiday_return",
    "operating_mode",
    "guest_mode_ends",
    "tank_thermal_state",
}
# Entities new in 0.9.0: the policy sensors and the three-state qualification.
ADDED_IN_0_9_0 = {
    "policy_state",
    "policy_mode",
    "soft_target",
    "target_reached",
    "heating_hours_needed",
    "measured_surplus_kw",
    "shadow_command",
    "setting_controller_three_state_qualified",
    "holiday_departure_date",
    "holiday_return_date",
}
