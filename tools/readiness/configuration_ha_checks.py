"""Real HA options-flow regression checks, only in disposable network-none CI."""

from copy import deepcopy
import json
from types import SimpleNamespace


async def check_configuration(hass, entry):
    from homeassistant.helpers import entity_registry as er
    from custom_components.thermann_shadow.config import (
        CLOUD_SOURCES,
        DEFAULT_OPTIONS,
        DEFAULT_SOURCES,
        OPTIONAL_SOURCES,
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
            "heating_preferences": ["solar_meters"],
            "ct_free_setup": ["solar_meters"],
            "diagnostic_report": [],
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
    # Blank command address, CT record and notification address are deliberately
    # optional in the real frontend. Its omission of empty fields is a no-op.
    data = {
        k: display_value(k, before[k])
        for k in PAGES["commissioning"]
        if k
        not in {
            "controller_command_topic",
            "heater_meter_verification",
            "controller_notify_service",
        }
    }
    result = await submit(await open_page("commissioning"), data)
    assert result["type"] == "create_entry" and dict(entry.options) == before, result
    hass.config_entries.async_update_entry(
        entry, options={**before, "controller_notify_service": "mobile_app_synthetic"}
    )
    await hass.async_block_till_done()
    result = await submit(await open_page("commissioning"), data)
    assert result["type"] == "create_entry" and dict(entry.options) == before, result

    for page in ("sources", "bridge_sources"):
        keys = [
            k
            for k in before["sources"]
            if k in (DEFAULT_SOURCES | OPTIONAL_SOURCES)
            and (k in CLOUD_SOURCES) == (page == "bridge_sources")
            and before["sources"][k]
        ]
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
    lead_options = {**before, "peak_command_lead_minutes": 5}
    hass.config_entries.async_update_entry(entry, options=lead_options)
    await hass.async_block_till_done()
    flow = await open_page("hot_water")
    data = {k: display_value(k, entry.options[k]) for k in PAGES["hot_water"]}
    result = await submit(flow, {**data, "completion_margin_minutes": 5})
    assert result["errors"] == {"base": "invalid_settings"} and dict(entry.options) == lead_options
    assert (
        result["data_schema"]({**data, "completion_margin_minutes": 5})["completion_margin_minutes"]
        == 5
    )
    hass.config_entries.options.async_abort(result["flow_id"])
    hass.config_entries.async_update_entry(entry, options=before)
    await hass.async_block_till_done()

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
    hass.config_entries.options.async_abort(result["flow_id"])

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
        hass.config_entries.options.async_abort(result["flow_id"])
        flow = await open_page("schedule")
        result = await submit(flow, {"action": "save"})
        assert result["errors"] == {"base": "locked_while_active"}, result
        assert "periods" in result["description_placeholders"]
        assert dict(entry.options) == before
        hass.config_entries.options.async_abort(result["flow_id"])
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
    hass.config_entries.options.async_abort(flow["flow_id"])

    # A completely empty draft remains editable, cannot save, and cancellation
    # leaves the original persisted tariff untouched.
    flow = await open_page("schedule")
    for _ in json.loads(entry.options["tariff_periods"]):
        flow = await submit(flow, {"action": "delete", "period": "0"})
        flow = await submit(flow, {"confirm": True})
    assert "period" not in {str(k) for k in flow["data_schema"].schema}
    flow = await submit(flow, {"action": "save"})
    assert flow["errors"] == {"base": "invalid_settings"}
    flow = await submit(flow, {"action": "add"})
    assert flow["step_id"] == "period" and dict(entry.options) == before
    hass.config_entries.options.async_abort(flow["flow_id"])

    # Clearing an optional mapping must not reinsert the suggested old value;
    # remapping the circuit still invalidates its qualifications exactly as before.
    flow = await open_page("sources")
    mapping = {
        k: v
        for k, v in before["sources"].items()
        if k in (DEFAULT_SOURCES | OPTIONAL_SOURCES) and k not in CLOUD_SOURCES and v
    }
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

    # Native report is read-only, including edited submitted text.
    flow = await open_page("diagnostic_report")
    data = flow["data_schema"]({})
    assert "Thermowatt diagnostic report" in data["report"]
    result = await submit(flow, {"report": "discard this edit"})
    assert result["type"] == "abort" and dict(entry.options) == before
    from custom_components.thermann_shadow.diagnostics import async_get_config_entry_diagnostics

    assert (await async_get_config_entry_diagnostics(hass, entry))["schema"] == 1

    # Genuine HA power states -> supported selectors -> compatible CT-free record.
    sources = {
        **before["sources"],
        "grid": "sensor.synthetic_signed_grid",
        "pv_ac": "sensor.synthetic_ac",
        "house": "sensor.synthetic_house",
        "heater_power": "",
    }
    hass.config_entries.async_update_entry(
        entry, options={**before, "sources": sources, "heater_meter_verification": ""}
    )
    await hass.async_block_till_done()
    for name, watts in (("grid", 4000), ("pv_ac", 5000), ("house", 1000)):
        hass.states.async_set(sources[name], watts, {"unit_of_measurement": "W"})
    flow = await open_page("ct_free_setup")
    data = {
        "direction": "export_positive",
        "confirm_direction": False,
        "accept_experimental": False,
        "enable_boost": True,
        "allow_peak": True,
    }
    flow = await submit(flow, data)
    assert flow["errors"]["base"] == "experimental_ack_required", flow
    flow = await submit(
        flow,
        {
            **data,
            "direction": "import_positive",
            "confirm_direction": True,
            "accept_experimental": True,
        },
    )
    assert flow["errors"]["base"] == "meter_not_ready", flow
    result = await submit(flow, {**data, "confirm_direction": True, "accept_experimental": True})
    assert result["type"] == "create_entry", result
    assert entry.options["ct_free_solar_verification"] == sources["grid"] + "|W|export_positive|3"
    assert (
        entry.options["controller_four_state_qualified"]
        == before["controller_four_state_qualified"]
    )
    assert entry.options["learning_hardware_qualified"] == before["learning_hardware_qualified"]
    assert hass.data[DOMAIN][entry.entry_id].executor.controller.enabled is False
    # A real PV dip/recovery in the same event-loop turn must break continuous
    # weekend evidence even though the later decision sees the recovered state.
    from homeassistant.util import dt as dt_util
    from datetime import timedelta

    pv_source = "sensor.synthetic_pv_events"
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "sources": {**sources, "pv": pv_source}}
    )
    await hass.async_block_till_done()
    runtime = hass.data[DOMAIN][entry.entry_id]
    now = dt_util.utcnow()
    for minute in range(16):
        runtime.executor.policy.add_pv(now - timedelta(minutes=15 - minute), 1)
    hass.states.async_set(pv_source, 100, {"unit_of_measurement": "W"})
    hass.states.async_set(pv_source, 1000, {"unit_of_measurement": "W"})
    await hass.async_block_till_done()
    assert not runtime.executor.policy.pv_sustained(
        dt_util.utcnow(), timedelta(minutes=15), lambda kw: kw >= 0.5
    )
    # Exercise real HA callbacks for a required-meter outage/recovery in one
    # loop turn. Every command is blocked by the absent MQTT/commissioning;
    # no fake physical qualification or service transport is provided.
    from custom_components.thermann_shadow.controller import Controller, NORMAL_ACTIVE
    from custom_components.thermann_shadow.targets import NORMAL

    peak_options = {
        **entry.options,
        "tariff_profile": "custom",
        "tariff_periods": json.dumps(
            [
                {
                    "days": list(range(7)),
                    "start": "00:00",
                    "end": "00:00",
                    "kind": "peak",
                    "rate": 0.36,
                }
            ]
        ),
        "tariff_verified": True,
    }
    hass.config_entries.async_update_entry(entry, options=peak_options)
    await hass.async_block_till_done()
    runtime = hass.data[DOMAIN][entry.entry_id]
    bridge_sources = runtime.sources
    now = dt_util.utcnow()
    hass.states.async_set(
        bridge_sources["heater"],
        "heat",
        {"temperature": 62, "current_temperature": 50, "unit_of_measurement": "°C"},
    )
    hass.states.async_set(bridge_sources["mode"], "Manual")
    hass.states.async_set(bridge_sources["last_poll"], now.isoformat())
    hass.states.async_set(
        bridge_sources["cloud_health"],
        "ok",
        {
            "auth_guard_mode": "authorized",
            "commands_enabled": True,
            "command_policy": "automation",
            "command_confirmation_pending": False,
            "command_transitions": ["off@62"],
            "consecutive_failures": 0,
        },
    )
    await hass.async_block_till_done()
    original_controller = runtime.executor.controller
    runtime.executor.controller = Controller(
        enabled=True, state=NORMAL_ACTIVE, heater=NORMAL, solar_session_active=True
    )
    hass.states.async_set(sources["grid"], "unavailable", {"unit_of_measurement": "W"})
    hass.states.async_set(sources["grid"], 3500, {"unit_of_measurement": "W"})
    await hass.async_block_till_done()
    assert runtime.executor.controller.protective_exit is not None
    assert runtime.executor._saved["protective_exit"] is not None
    assert runtime.executor.controller.intent is None
    runtime.executor.controller = original_controller
    runtime.solar_input_loss_pending = False
    await runtime.executor._save()
    hass.config_entries.async_update_entry(entry, options=before)
    await hass.async_block_till_done()

    # Discard the scenario's old shadow decision before browser screenshots;
    # show the restored actual options and a matching read-only evaluation.
    runtime = hass.data[DOMAIN][entry.entry_id]
    runtime.update(dt_util.utcnow())
    await runtime.executor.async_step(dt_util.utcnow())
    assert (
        hass.states.get("sensor.thermann_shadow_current_heating_plan").state
        == runtime.executor.policy_values()["plan_summary"]
    )
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
