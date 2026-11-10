"""Phase 2B checks for shadow_ha_smoke.py. Runs ONLY inside an isolated HA Core
container with --network none. Never import this on the owner's Home Assistant.

- every native settings entity, driven through the REAL HA service layer;
- invalid combinations, atomic saves, restore and undo;
- every dashboard entity reference and every markdown template rendered by HA;
- forecast-present, Forecast.Solar, flat-baseline and invalid/stale paths;
- a genuine 0.2.0 -> 0.3.0 upgrade over persisted HA storage.
"""

from datetime import timedelta
import json
from pathlib import Path
import re
import shutil
import sys

import yaml

from homeassistant import bootstrap, config_entries, loader
from homeassistant.core import HomeAssistant, ServiceRegistry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.template import Template
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import METRIC_SYSTEM

ROOT = Path("/workspace")
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


async def upgrade_from_0_2_0(folder):
    hass = await start_hass(folder, LEGACY)
    integration = await loader.async_get_custom_components(hass)
    assert integration["thermann_shadow"].version.__str__() == "0.2.0"
    from custom_components.thermann_shadow.config import DEFAULT_OPTIONS, DEFAULT_SOURCES
    from custom_components.thermann_shadow.sensor import SENSORS as LEGACY_SENSORS

    result = await hass.config_entries.flow.async_init(
        "thermann_shadow", context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], DEFAULT_SOURCES)
    assert result["type"] == "create_entry", result
    entry = result["result"]
    await hass.async_block_till_done()
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], DEFAULT_SOURCES)
    legacy = {
        **DEFAULT_OPTIONS,
        "target_c": 65.0,
        "margin_minutes": 45.0,
        "import_positive": False,
        "tariff_periods": LEGACY_CUSTOM_TARIFF,
    }
    saved = await hass.config_entries.options.async_configure(flow["flow_id"], legacy)
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
    assert len(before) == len(LEGACY_SENSORS) == 35
    assert "sensor.hot_water_shadow_controller" in before.values()
    saved_options = dict(entry.options)
    entry_id = entry.entry_id
    await hass.async_stop()  # final write of config entries and entity registry

    hass = await start_hass(folder, ROOT / "custom_components/thermann_shadow")
    integration = await loader.async_get_custom_components(hass)
    assert integration["thermann_shadow"].version.__str__() == "0.3.0"
    (entry,) = hass.config_entries.async_entries("thermann_shadow")
    assert entry.entry_id == entry_id and dict(entry.options) == saved_options
    assert await async_setup_component(hass, "thermann_shadow", {})
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED, entry.state
    assert dict(entry.options) == saved_options  # loading never rewrites options
    runtime = hass.data["thermann_shadow"][entry.entry_id]
    assert runtime.settings.target_c == 65 and runtime.settings.margin_minutes == 45
    assert len(runtime.tariffs) == 1 and runtime.tariffs[0].kind == "off_peak"
    registry = er.async_get(hass)
    after = {
        item.unique_id: item.entity_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert {key: after[key] for key in before} == before  # identities and renames kept
    for entity_id in after.values():
        assert hass.states.get(entity_id) is not None, entity_id
    report_inputs(hass, DEFAULT_SOURCES)
    runtime.update(dt_util.utcnow())
    assert hass.states.get("select.thermann_shadow_tariff_periods_mode").state == "custom"
    assert hass.states.get("number.thermann_shadow_afternoon_storage_target").state == "65.0"
    controller = hass.states.get("sensor.hot_water_shadow_controller")
    assert controller.attributes["control_capable"] is False
    json.dumps(dict(controller.attributes), allow_nan=False)
    await hass.async_stop()
    return {"legacy_entities": len(before), "entities_after_upgrade": len(after)}


# --- Native settings through the real service layer --------------------------------


def alternate(key, meta, default):
    """A valid non-default value for each setting, in isolation."""
    if meta.kind == "switch":
        return not default
    if meta.kind == "select":
        return next(choice for choice in meta.choices if choice != default)
    if meta.kind == "text":
        return "2026-10-05"
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
        if meta.kind == "form":
            continue
        entity_id = entity_for(key)
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        attrs = state.attributes
        assert attrs["recommended_default"] == DEFAULT_OPTIONS[key], key
        assert attrs["original_default"] == DEFAULT_OPTIONS[key], key
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
        ("time", "set_value", entity_for("morning_time"), {"time": "12:30:00"}),
        ("time", "set_value", entity_for("evening_time"), {"time": "11:00:00"}),
        ("text", "set_value", entity_for("native_clock_check_date"), {"value": "2026-13-01"}),
        ("number", "set_value", entity_for("target_c"), {"value": 64}),
        ("number", "set_value", entity_for("t_comfort_reference_c"), {"value": 74}),
    ]
    for domain, service, entity_id, data in invalid:
        await rejected(hass, entry, drive(hass, domain, service, entity_id, **data))
    # Restore and undo, through confirmed-dashboard button services.
    await set_setting(hass, entity_for("target_c"), "number", 66)
    await set_setting(hass, entity_for("peak_rate"), "number", 0.4)
    await set_setting(hass, entity_for("forecast_enabled"), "switch", True)
    await drive(hass, "button", "press", "button.thermann_shadow_restore_recommended_preferences")
    assert entry.options["target_c"] == 70 and entry.options["forecast_enabled"] is False
    assert entry.options["peak_rate"] == 0.4  # tariff contract preserved
    assert entry.options[BACKUP_KEY] == {"target_c": 66, "forecast_enabled": True}
    assert runtime.settings.target_c == 70
    assert hass.states.get("button.thermann_shadow_undo_last_restore").state != "unavailable"
    await drive(hass, "button", "press", "button.thermann_shadow_undo_last_restore")
    assert entry.options["target_c"] == 66 and entry.options["forecast_enabled"] is True
    assert BACKUP_KEY not in entry.options and runtime.settings.target_c == 66
    assert hass.states.get("button.thermann_shadow_undo_last_restore").state == "unavailable"
    assert set(RESTORED) & {"peak_rate", "meter_verified", "import_positive"} == set()
    await drive(hass, "button", "press", "button.thermann_shadow_restore_recommended_preferences")
    await set_setting(hass, entity_for("peak_rate"), "number", DEFAULT_OPTIONS["peak_rate"])
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
    from custom_components.thermann_shadow.config import DEFAULT_OPTIONS, DEFAULT_SOURCES

    pv_id, load_id = "sensor.thermann_test_pv_forecast", "sensor.thermann_test_load_forecast"
    now = dt_util.utcnow().isoformat()
    emhass_state(hass, pv_id, "p_pv_forecast", 4500, now)
    emhass_state(hass, load_id, "p_load_forecast", 600, now)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    mapping = {**DEFAULT_SOURCES, "forecast_pv": pv_id, "forecast_load": load_id}
    flow = await hass.config_entries.options.async_configure(flow["flow_id"], mapping)
    assert flow["step_id"] == "settings"
    values = {key: entry.options.get(key, value) for key, value in DEFAULT_OPTIONS.items()}
    saved = await hass.config_entries.options.async_configure(
        flow["flow_id"], {**values, "forecast_enabled": True}
    )
    assert saved["type"] == "create_entry", saved
    await hass.async_block_till_done()
    runtime = hass.data["thermann_shadow"][entry.entry_id]
    assert runtime.sources["forecast_pv"] == pv_id and runtime.settings.forecast_enabled
    # Mapping change resets freshness: generation must be after the new start.
    generated = dt_util.utcnow().isoformat()
    emhass_state(hass, pv_id, "p_pv_forecast", 4500, generated)
    emhass_state(hass, load_id, "p_load_forecast", 600, generated)
    report_inputs(hass, DEFAULT_SOURCES, temperature=55, grid=3000, pv=4500)
    runtime.update(dt_util.utcnow())
    results = {}
    assert runtime.forecast.source == "published_pv_and_house_load", runtime.forecast.warnings
    assert runtime.forecast.load_basis == "published_household_load_forecast"
    assert runtime.details["forecast"]["intervals"] > 0
    surplus = hass.states.get("sensor.thermann_shadow_forecast_net_surplus")
    expected = 4.5 * 0.75 - 0.6 * 1.25 - 0.3
    assert abs(float(surplus.state) - expected) < 0.01, surplus.state
    assert float(hass.states.get("sensor.thermann_shadow_forecast_age").state) < 5
    results["emhass"] = runtime.values["decision"]
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
    results["forecast_solar_flat_load"] = runtime.values["decision"]
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
        assert not runtime.forecast.slots and runtime.plan.grid_fallback_start is not None
        assert runtime.values["forecast_net_surplus_kw"] is None
        assert runtime.values["decision"] != "wait_for_forecast_solar", label
        results[label] = runtime.values["decision"]
        validate_dashboard(hass, f"forecast_{label}")
    # Switch back off through the settings entity; mappings stay saved.
    await set_setting(hass, entity_for("forecast_enabled"), "switch", False)
    assert entry.options["sources"]["forecast_pv"] == pv_id
    assert runtime.forecast.source == "disabled"
    return results
