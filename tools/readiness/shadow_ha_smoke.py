"""Run inside the official HA Core image with --network none, never on owner HA."""

import asyncio
from dataclasses import replace
from datetime import timedelta
import json
import logging
from pathlib import Path
import socket
import tempfile
from types import MappingProxyType, SimpleNamespace

from homeassistant.core import Event, State
from homeassistant import config_entries, loader
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.components.recorder.const import SupportedDialect
from homeassistant.components.recorder.db_schema import StateAttributes
from homeassistant.components.websocket_api.commands import handle_get_states
from homeassistant.components.websocket_api.messages import cached_state_diff_message
from homeassistant.util import dt as dt_util
from homeassistant.helpers import entity_registry as er
from sqlalchemy import create_engine, select

from shadow_ha_checks import (
    DRIVER,
    check_controller,
    check_forecasts,
    check_unchanged_mqtt_payload_freshness,
    check_settings_services,
    install_service_guard,
    start_hass,
    upgrade_from_0_2_0,
    upgrade_from_0_3_0,
    upgrade_from_0_5_0,
    upgrade_from_0_6_0,
    upgrade_from_0_6_1,
    validate_dashboard,
)

ROOT = Path("/workspace")


def denied(*args, **kwargs):
    raise AssertionError("Shadow integration attempted external I/O or a service call")


def assert_entity_serialization(hass, sources):
    """Exercise actual get_states, state-change frames and Recorder encoders/SQL."""
    states = [
        state
        for state in hass.states.async_all()
        if state.entity_id.split(".", 1)[1].startswith("thermann_shadow_")
    ]
    from custom_components.thermann_shadow.sensor import CONTROLLER_SENSORS, SENSORS
    from custom_components.thermann_shadow.settings import CATALOG

    settings = sum(meta.kind != "form" for meta in CATALOG.values())
    # + restore/undo buttons; 0.5.0: controller sensors, master switch, 3 owner buttons.
    expected = len(SENSORS) + settings + 2 + len(CONTROLLER_SENSORS) + 1 + 3
    assert len(states) == expected, (len(states), expected)
    frames = []
    connection = SimpleNamespace(
        user=SimpleNamespace(is_admin=True),
        send_message=frames.append,
        logger=logging.getLogger(__name__),
    )
    handle_get_states(hass, connection, {"id": 1, "type": "get_states"})
    response = json.loads(frames[0])
    assert response["success"] is True
    returned = {state["entity_id"]: state for state in response["result"]}
    assert all(state.entity_id in returned for state in states)  # no silent omission
    assert returned["sensor.thermann_shadow_controller"]["attributes"]["sources"] == dict(sources)
    engine = create_engine("sqlite:///:memory:")
    try:
        StateAttributes.__table__.create(engine)
        with engine.begin() as db:
            for state in states:
                event = Event(
                    EVENT_STATE_CHANGED,
                    {"entity_id": state.entity_id, "old_state": None, "new_state": state},
                    context=state.context,
                )
                frame = json.loads(cached_state_diff_message(b"2", event))
                assert frame["type"] == "event"
                attrs = frame["event"]["a"][state.entity_id]["a"]
                encoded = StateAttributes.shared_attrs_bytes_from_event(
                    event, SupportedDialect.SQLITE
                )
                pg_encoded = StateAttributes.shared_attrs_bytes_from_event(
                    event, SupportedDialect.POSTGRESQL
                )
                if state.entity_id == "sensor.thermann_shadow_controller":
                    assert attrs["sources"] == dict(sources)
                    assert json.loads(encoded)["sources"] == dict(sources)
                    assert json.loads(pg_encoded)["sources"] == dict(sources)
                row = db.execute(
                    StateAttributes.__table__.insert().values(
                        hash=StateAttributes.hash_shared_attrs_bytes(encoded),
                        shared_attrs=encoded.decode("utf-8"),
                    )
                )
                stored = db.execute(
                    select(StateAttributes.shared_attrs).where(
                        StateAttributes.attributes_id == row.inserted_primary_key[0]
                    )
                ).scalar_one()
                assert json.loads(stored) == json.loads(encoded)
    finally:
        engine.dispose()


def assert_original_mappingproxy_failure_is_detected(hass, sources):
    """Negative control: HA storage alone accepts attrs that both paths reject."""
    controller = hass.states.get("sensor.thermann_shadow_controller")
    bad = State(
        controller.entity_id,
        controller.state,
        {**controller.attributes, "sources": MappingProxyType(dict(sources))},
    )
    try:
        _ = bad.as_dict_json  # encoder used by WebSocket get_states
    except TypeError:
        pass
    else:
        raise AssertionError("WebSocket negative control failed")
    event = Event(
        EVENT_STATE_CHANGED, {"entity_id": bad.entity_id, "old_state": None, "new_state": bad}
    )
    try:
        StateAttributes.shared_attrs_bytes_from_event(event, SupportedDialect.SQLITE)
    except TypeError:
        pass
    else:
        raise AssertionError("Recorder negative control failed")


async def main():
    # No connection or DNS at all; service calls only from the explicit test
    # driver, and only to this integration's local settings entities.
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied
    socket.getaddrinfo = denied
    install_service_guard()
    with tempfile.TemporaryDirectory() as legacy:
        upgrade = await upgrade_from_0_2_0(legacy)
    with tempfile.TemporaryDirectory() as installed:
        upgrade_030 = await upgrade_from_0_3_0(installed)
    with tempfile.TemporaryDirectory() as installed_050:
        upgrade_050 = await upgrade_from_0_5_0(installed_050)
    with tempfile.TemporaryDirectory() as installed_060:
        upgrade_060 = await upgrade_from_0_6_0(installed_060)
    with tempfile.TemporaryDirectory() as installed_061:
        upgrade_061 = await upgrade_from_0_6_1(installed_061)
    with tempfile.TemporaryDirectory() as folder:
        hass = await start_hass(folder, ROOT / "custom_components/thermann_shadow")
        assert "thermann_shadow" in await loader.async_get_config_flows(hass)
        descriptions = await loader.async_get_integration_descriptions(hass)
        listed = descriptions["custom"]["integration"]["thermann_shadow"]
        assert listed["integration_type"] == "hub" and listed["config_flow"] is True
        result = await hass.config_entries.flow.async_init(
            "thermann_shadow", context={"source": "user"}
        )
        assert result["type"] == "form"
        from custom_components.thermann_shadow.config import (
            DEFAULT_OPTIONS,
            DEFAULT_SOURCES,
            DOMAIN,
        )
        from custom_components.thermann_shadow.model import Reading, evaluate

        result = await hass.config_entries.flow.async_configure(result["flow_id"], DEFAULT_SOURCES)
        assert result["type"] == "create_entry", result
        entry = result["result"]
        await hass.async_block_till_done()
        assert entry.state is config_entries.ConfigEntryState.LOADED, entry.state
        runtime = hass.data[DOMAIN][entry.entry_id]
        assert isinstance(runtime.sources, MappingProxyType)
        assert runtime.plan.state == "shadow_blocked"
        assert_entity_serialization(hass, runtime.sources)
        assert_original_mappingproxy_failure_is_detected(hass, runtime.sources)
        now = dt_util.utcnow()
        values = {
            "heater": ("unknown", {"current_temperature": 63, "temperature": 70}),
            "mode": ("Schedule", {}),
            "last_poll": (now.isoformat(), {}),
            "cloud_health": ("ok", {}),
            "requests": (4, {"accounting_complete": True, "accounting_persistent": True}),
            "grid": (1501, {"unit_of_measurement": "W"}),
            "pv": (2322, {"unit_of_measurement": "W"}),
            "house": (821, {"unit_of_measurement": "W"}),
            "import_energy": (1234, {"unit_of_measurement": "kWh"}),
            "export_energy": (5678, {"unit_of_measurement": "kWh"}),
        }
        for key, (state, attrs) in values.items():
            hass.states.async_set(DEFAULT_SOURCES[key], state, attrs)
        now = dt_util.utcnow()
        runtime.update(now)
        assert runtime.plan.state not in {"shadow_blocked", "shadow_awaiting_validation"}
        assert runtime.values["temperature"] == 63
        assert runtime.values["target"] == 70
        assert runtime.values["measured_net_export_kw"] == 1.501
        assert runtime.values["pv"] == 2.322
        assert runtime.values["requests_since_start"] == 0
        assert runtime.plan.current_price_aud in {0.170200, 0.361878}
        assert runtime.details["additional_cloud_requests"] == 0
        assert runtime.details["control_capable"] is False
        assert runtime.details["observed_refresh_pattern_attempts_per_day"] == 144
        assert_entity_serialization(hass, runtime.sources)
        # Real config/options flows reject bad tariffs; owner can edit mappings.
        flow = await hass.config_entries.options.async_init(entry.entry_id)
        flow = await hass.config_entries.options.async_configure(flow["flow_id"], DEFAULT_SOURCES)
        assert flow["step_id"] == "settings"
        # The stored custom table is validated in BOTH profiles; an invalid
        # table must re-show the form with an error, never create an entry.
        for bad in (
            {"tariff_periods": "[]"},
            {"tariff_profile": "custom", "tariff_periods": "[]"},
            {"peak_morning_end": "17:00:00"},
        ):
            flow = await hass.config_entries.options.async_configure(flow["flow_id"], bad)
            assert flow["type"] == "form" and flow["step_id"] == "settings", flow
            assert flow["errors"] == {"base": "invalid_settings"}, flow
            assert entry.options == {}, entry.options
        # Explicit synthetic-only qualified settings exercise planning on real HA states.
        runtime.settings = replace(runtime.settings, meter_verified=True, tariff_verified=True)
        runtime.update(now)
        assert runtime.plan.state != "shadow_blocked"
        hass.states.async_set(
            DEFAULT_SOURCES["requests"],
            7,
            {"accounting_complete": True, "accounting_persistent": True},
        )
        runtime.update(dt_util.utcnow())
        assert runtime.values["requests_since_start"] == 3
        hass.states.async_set(DEFAULT_SOURCES["requests"], 1)
        runtime.update(dt_util.utcnow())
        assert "request_counter_reset_history_incomplete" in runtime.plan.warnings
        hass.states.async_set(DEFAULT_SOURCES["mode"], "Manual")
        runtime.update(dt_util.utcnow())
        assert runtime.plan.state == "shadow_native_intervention"
        hass.states.async_set(DEFAULT_SOURCES["mode"], "Schedule")
        runtime.update(dt_util.utcnow())
        assert runtime.plan.state == "shadow_native_intervention"  # latched for review
        runtime.intervention = False
        hass.states.async_set(DEFAULT_SOURCES["cloud_health"], "quota_limited")
        runtime.update(dt_util.utcnow())
        assert runtime.plan.state == "shadow_blocked"
        assert_entity_serialization(hass, runtime.sources)
        # A fresh HA report of old retained cloud data is not a new poll after restart.
        fresh = {
            key: Reading(value, now, "°C" if key in {"target", "temperature"} else "W")
            for key, value in {
                "temperature": 63,
                "target": 70,
                "mode": "Schedule",
                "cloud_health": "ok",
                "last_poll": (now - timedelta(hours=1)).isoformat(),
                "grid": 1501,
            }.items()
        }
        assert (
            evaluate(now, runtime.boot, fresh, runtime.settings, runtime.tariffs).state
            == "shadow_blocked"
        )
        controller = hass.states.get("sensor.thermann_shadow_controller")
        assert controller is not None
        assert controller.attributes["control_capable"] is False
        sensor_ids = [
            state.entity_id
            for state in hass.states.async_all("sensor")
            if state.entity_id.startswith("sensor.thermann_shadow_")
        ]
        from custom_components.thermann_shadow.sensor import CONTROLLER_SENSORS, SENSORS

        assert len(sensor_ids) == len(SENSORS) + len(CONTROLLER_SENSORS), sensor_ids
        # Save through the real options flow. Reload retains entity identities,
        # releases listeners, keeps validation false and waits for a normal poll.
        old_runtime = runtime
        saved = await hass.config_entries.options.async_configure(flow["flow_id"], DEFAULT_OPTIONS)
        assert saved["type"] == "create_entry"
        await hass.async_block_till_done()
        assert entry.state is config_entries.ConfigEntryState.LOADED
        runtime = hass.data[DOMAIN][entry.entry_id]
        assert runtime is old_runtime  # preference saves recalculate, not reload
        assert runtime.settings.meter_verified and runtime.settings.tariff_verified
        assert runtime.plan.state == "shadow_blocked"
        assert entry.options["sources"] == DEFAULT_SOURCES
        runtime.sources = MappingProxyType(dict(runtime.sources))
        runtime.update(dt_util.utcnow())
        assert_entity_serialization(hass, runtime.sources)
        # Native dashboard controls and Configure share one authoritative entry.
        from custom_components.thermann_shadow.settings import CATALOG

        registry = er.async_get(hass)

        def entity_for(key):
            entity_id = registry.async_get_entity_id(
                CATALOG[key].kind, DOMAIN, f"{entry.entry_id}_setting_{key}"
            )
            assert entity_id, key
            return entity_id

        dashboard_refs, dashboard_templates = validate_dashboard(hass, "blocked")
        settings_checked = await check_settings_services(hass, entry, runtime, entity_for)
        assert runtime is old_runtime  # local saves recalculate; never a reload
        assert entry.options["sources"] == DEFAULT_SOURCES
        validate_dashboard(hass, "after_settings")
        assert_entity_serialization(hass, runtime.sources)
        # Actual unload/setup simulates HA restart, preserving options and IDs.
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        runtime = hass.data[DOMAIN][entry.entry_id]
        assert runtime is not old_runtime and not old_runtime.listeners
        assert runtime.advisor.shown is None or runtime.plan.state == "shadow_blocked"
        assert set(sensor_ids) == {
            state.entity_id
            for state in hass.states.async_all("sensor")
            if state.entity_id.startswith("sensor.thermann_shadow_")
        }
        freshness = await check_unchanged_mqtt_payload_freshness(hass, entry)
        forecast_paths = await check_forecasts(hass, entry, entity_for)
        controller = await check_controller(hass, entry, entity_for)
        runtime = hass.data[DOMAIN][entry.entry_id]
        assert_entity_serialization(hass, runtime.sources)
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert not runtime.listeners
        await hass.async_stop()
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "real_ha_config_flow": "PASS",
                    "sensor_count": len(sensor_ids),
                    "unknown_water_heater_attributes": "PASS",
                    "request_replay_accounting": "PASS",
                    "manual_intervention_latch": "PASS",
                    "options_reload_and_ids": "PASS",
                    "native_preference_controls_and_restore": "PASS",
                    "settings_entities_driven_through_ha_services": settings_checked,
                    "settings_service_calls": DRIVER["calls"],
                    "restore_undo_and_atomic_rejections": "PASS",
                    "dashboard_entity_references_resolved": dashboard_refs,
                    "dashboard_templates_rendered": dashboard_templates,
                    "forecast_paths": forecast_paths,
                    "upgrade_0_2_0_to_0_7_0": upgrade,
                    "upgrade_0_3_0_to_0_7_0": upgrade_030,
                    "upgrade_0_5_0_to_0_7_0": upgrade_050,
                    "upgrade_0_6_0_to_0_7_0": upgrade_060,
                    "upgrade_0_6_1_to_0_7_0": upgrade_061,
                    "unchanged_mqtt_payload_freshness": freshness,
                    "controller_0_7_0": controller,
                    "add_integration_hub_listing": "PASS",
                    "websocket_states_and_events_json": "PASS",
                    "recorder_attributes_and_sqlite_roundtrip": "PASS",
                    "mappingproxy_negative_control": "PASS",
                    "clean_unload": "PASS",
                    "live_cloud_requests": 0,
                    "integration_service_calls": 0,
                    "heater_commands": 0,
                }
            )
        )


asyncio.run(main())
