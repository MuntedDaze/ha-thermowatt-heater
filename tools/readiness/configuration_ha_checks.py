"""Real HA options-flow regression checks, only in disposable network-none CI."""

from copy import deepcopy
import json
from types import SimpleNamespace


async def check_configuration(hass, entry):
    from homeassistant.helpers import entity_registry as er
    from custom_components.thermann_shadow.config import (
        CLOUD_SOURCES,
        DEFAULT_OPTIONS,
        saved_options,
    )
    from custom_components.thermann_shadow.configuration import MENUS, PAGES, display_value
    from custom_components.thermann_shadow.config_flow import ShadowOptionsFlow
    from custom_components.thermann_shadow import DOMAIN

    original = deepcopy(dict(entry.options))
    ids = {e.unique_id: e.entity_id for e in er.async_get(hass).entities.values()}

    async def open_page(page):
        flow = await hass.config_entries.options.async_init(entry.entry_id)
        path = {
            "hot_water": [],
            "sources": ["solar_meters"],
            "bridge_sources": ["advanced"],
            "solar": ["solar_meters"],
            "prices": ["electricity"],
            "peak_times": ["electricity"],
            "tariff_json": ["electricity"],
            "schedule": ["electricity"],
        }.get(page, ["advanced"])
        assert set(flow["menu_options"]) == set(MENUS["init"])
        for step in [*path, page]:
            flow = await hass.config_entries.options.async_configure(
                flow["flow_id"], {"next_step_id": step}
            )
        assert flow["step_id"] == page, flow
        return flow

    async def submit(flow, data):
        result = await hass.config_entries.options.async_configure(flow["flow_id"], data)
        await hass.async_block_till_done()
        return result

    # Each new page is a complete no-op over a representative persisted 0.13
    # configuration, including precise retail prices, household targets, unknown
    # extension data and the Restore/Undo snapshot. No storage migration is needed.
    for page, keys in PAGES.items():
        before = deepcopy(dict(entry.options))
        values = saved_options(before)
        flow = await open_page(page)
        result = await submit(flow, {k: display_value(k, values[k]) for k in keys})
        assert result["type"] == "create_entry", result
        assert dict(entry.options) == before, page

    before = deepcopy(dict(entry.options))
    for page in ("sources", "bridge_sources"):
        keys = [k for k in before["sources"] if (k in CLOUD_SOURCES) == (page == "bridge_sources")]
        result = await submit(await open_page(page), {k: before["sources"][k] for k in keys})
        assert result["type"] == "create_entry", result
        assert dict(entry.options) == before

    flow = await open_page("prices")
    data = {k: display_value(k, entry.options[k]) for k in PAGES["prices"]}
    result = await submit(flow, {**data, "peak_rate": 36.1878123456})
    assert result["type"] == "create_entry", result
    assert entry.options["peak_rate"] == 0.361878123456
    hass.config_entries.async_update_entry(entry, options=before)
    await hass.async_block_till_done()

    # Invalid target combination redisplays submitted values and saves nothing.
    flow = await open_page("hot_water")
    data = {k: display_value(k, entry.options[k]) for k in PAGES["hot_water"]}
    result = await submit(flow, {**data, "normal_storage_c": "70", "solar_boost_c": "62"})
    assert result["errors"] == {"base": "invalid_settings"}, result
    assert dict(entry.options) == before
    assert (
        result["data_schema"]({**data, "normal_storage_c": "70", "solar_boost_c": "62"})[
            "normal_storage_c"
        ]
        == "70"
    )
    await hass.config_entries.options.async_abort(result["flow_id"])

    # The unchanged active-control lock applies to converted prices and the
    # guided schedule. Stub only the switch's state, never any command transport.
    real_runtime = hass.data[DOMAIN][entry.entry_id]
    hass.data[DOMAIN][entry.entry_id] = SimpleNamespace(
        executor=SimpleNamespace(controller=SimpleNamespace(enabled=True))
    )
    try:
        flow = await open_page("prices")
        data = {k: display_value(k, entry.options[k]) for k in PAGES["prices"]}
        result = await submit(flow, {**data, "off_peak_rate": 25})
        assert result["errors"] == {"base": "locked_while_active"}, result
        assert dict(entry.options) == before
        await hass.config_entries.options.async_abort(result["flow_id"])
        flow = await open_page("schedule")
        result = await submit(flow, {"action": "save"})
        assert result["errors"] == {"base": "locked_while_active"}, result
        assert dict(entry.options) == before
        await hass.config_entries.options.async_abort(result["flow_id"])
    finally:
        hass.data[DOMAIN][entry.entry_id] = real_runtime

    flow = await open_page("schedule")
    flow = await submit(flow, {"action": "edit", "period": "0"})
    assert flow["step_id"] == "period"
    rows = json.loads(entry.options["tariff_periods"])
    first = rows[0]
    flow = await submit(
        flow,
        {
            "days": [str(d) for d in first["days"]],
            "start": first["start"],
            "end": first["end"],
            "kind": first["kind"],
            "months": [str(m) for m in first.get("months", range(1, 13))],
            "use_rate": True,
            "rate": 12.3456789123,
        },
    )
    assert flow["step_id"] == "schedule" and dict(entry.options) == before
    result = await submit(flow, {"action": "save"})
    assert result["type"] == "create_entry", result
    assert entry.options["tariff_profile"] == "custom"
    assert json.loads(entry.options["tariff_periods"])[0]["rate"] == 0.123456789123
    assert entry.options["tariff_verified"] == before["tariff_verified"]
    hass.config_entries.async_update_entry(entry, options=before)
    await hass.async_block_till_done()

    flow = await open_page("schedule")
    flow = await submit(flow, {"action": "delete", "period": "0"})
    flow = await submit(flow, {"confirm": True})
    flow = await submit(flow, {"action": "save"})
    assert flow["errors"] == {"base": "invalid_settings"}, flow
    assert dict(entry.options) == before
    await hass.config_entries.options.async_abort(flow["flow_id"])

    # Clearing an optional mapping must not reinsert the suggested old value;
    # remapping the circuit still invalidates its qualifications exactly as before.
    flow = await open_page("sources")
    mapping = {k: v for k, v in before["sources"].items() if k not in CLOUD_SOURCES}
    result = await submit(flow, {**mapping, "heater_power": "sensor.synthetic_new_power"})
    assert result["type"] == "create_entry", result
    assert entry.options["heater_meter_verification"] == ""
    assert entry.options["learning_hardware_qualified"] is False
    flow = await open_page("sources")
    result = await submit(flow, mapping)
    assert result["type"] == "create_entry", result
    assert "heater_power" not in entry.options["sources"]
    hass.config_entries.async_update_entry(entry, options=before)
    await hass.async_block_till_done()

    assert ids == {e.unique_id: e.entity_id for e in er.async_get(hass).entities.values()}
    assert dict(entry.options) == original
    assert ShadowOptionsFlow(entry)._entry.unique_id == entry.unique_id
    assert all(
        entry.options[k] == DEFAULT_OPTIONS[k]
        for k in ("baseline_c", "normal_storage_c", "solar_boost_c")
    )
    return {
        "pages": len(PAGES),
        "saved_values_and_ids_preserved": True,
        "control_and_transport": "disabled",
    }
