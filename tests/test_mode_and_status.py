"""Existing cloud responses only; exercise the MQTT Jinja templates with synthetic data."""

import json

from jinja2 import Environment, StrictUndefined
import pytest

from conftest import STATUS, authenticate, response

TEMPLATES = Environment(undefined=StrictUndefined)


def discoveries(bridge):
    bridge.publish_discovery("TEST123", "Synthetic heater")
    return {
        call.args[0]: json.loads(call.args[1])
        for call in bridge.mqtt_client.publish.call_args_list
        if call.args[0].endswith("/config")
    }


def render(template, status):
    return TEMPLATES.from_string(template).render(value_json=status)


@pytest.mark.parametrize(
    "cmd,vendor,ha_mode",
    [
        (9, "Manual", "performance"),
        (3, "Eco", "eco"),
        (17, "Schedule", "None"),
        (65, "Holiday", "None"),
        (16, "Off", "off"),
        (0, "Unknown", "None"),
        (99, "Unknown", "None"),
        (257, "Unknown", "None"),
    ],
)
def test_vendor_mode_and_native_ha_mode_are_not_confused(factory, cmd, vendor, ha_mode):
    bridge = factory()
    authenticate(bridge)
    configs = discoveries(bridge)
    cloud = {"result": {**STATUS["result"], "Cmd": str(cmd), "T_Avg": "17", "T_SetPoint": "70"}}
    bridge.session.request.side_effect = [response(body=cloud)]
    bridge.poll_status("TEST123")
    state = next(
        json.loads(call.args[1])
        for call in bridge.mqtt_client.publish.call_args_list
        if call.args[0] == "P/TEST123/STATUS"
    )
    heater = configs["homeassistant/water_heater/TEST123/config"]
    sensor = configs["homeassistant/sensor/TEST123/vendor_mode/config"]
    assert render(heater["mode_state_template"], state) == ha_mode
    assert render(sensor["value_template"], state) == vendor
    assert float(render(heater["current_temperature_template"], state)) == 17
    assert float(render(heater["temperature_state_template"], state)) == 70
    assert bridge.availability["TEST123"] is True
    assert heater["unique_id"] == "thermowatt_TEST123_v314"
    assert sensor["unique_id"] == "thermowatt_TEST123_vendor_mode"
    assert sensor["device"] == heater["device"]
    assert sensor["availability"] == heater["availability"]
    assert not any("command" in key for key in sensor)
    attributes = json.loads(render(sensor["json_attributes_template"], state))
    assert attributes == {"Cmd": str(cmd), "WaterHeaterSts": "1", "heating_status_verified": False}
    assert bridge.session.request.call_count == 1
    assert bridge.session.request.call_args.args[0] == "GET"


@pytest.mark.parametrize("raw", [0, 1, 2, 3, 4, 9, 16, 17, 65, 128, 255, 65535])
def test_no_unverified_status_bit_means_physical_heating(factory, raw):
    bridge = factory()
    authenticate(bridge)
    configs = discoveries(bridge)
    bridge.session.request.side_effect = [
        response(
            body={
                "result": {
                    **STATUS["result"],
                    "WaterHeaterSts": str(raw),
                }
            }
        )
    ]
    bridge.poll_status("TEST123")
    state = next(
        json.loads(call.args[1])
        for call in bridge.mqtt_client.publish.call_args_list
        if call.args[0] == "P/TEST123/STATUS"
    )
    assert state["result"]["WaterHeaterSts"] == str(raw)
    assert state["result"]["heating"] is None
    heating = configs["homeassistant/binary_sensor/TEST123/heating/config"]
    assert heating["unique_id"] == "thermowatt_TEST123_heating"
    # HA MQTT binary_sensor's None payload explicitly resets to unknown, not OFF.
    assert render(heating["value_template"], state) == "None"


@pytest.mark.parametrize("legacy", [True, False, None])
def test_discovery_upgrade_cannot_reuse_retained_heating_claim(factory, legacy):
    configs = discoveries(factory())
    old_status = {"result": {**STATUS["result"], "heating": legacy}}
    heating = configs["homeassistant/binary_sensor/TEST123/heating/config"]
    vendor = configs["homeassistant/sensor/TEST123/vendor_mode/config"]
    assert render(heating["value_template"], old_status) == "None"
    assert render(vendor["value_template"], old_status) == "Unknown"


@pytest.mark.parametrize(
    "field,bad",
    [
        ("Cmd", -1),
        ("Cmd", 17.5),
        ("Cmd", "bad"),
        ("WaterHeaterSts", -1),
        ("WaterHeaterSts", 1.5),
        ("WaterHeaterSts", {}),
        ("T_Avg", "nan"),
        ("T_SetPoint", None),
    ],
)
def test_malformed_status_still_never_publishes_state(factory, module, field, bad):
    bridge = factory()
    authenticate(bridge)
    bridge.session.request.side_effect = [
        response(body={"result": {**STATUS["result"], field: bad}})
    ]
    with pytest.raises(module.CloudError):
        bridge.poll_status("TEST123")
    assert not any(
        call.args[0].endswith("/STATUS") for call in bridge.mqtt_client.publish.call_args_list
    )


def test_schedule_or_sensitive_fields_in_status_are_not_implicitly_exposed(factory):
    bridge = factory()
    authenticate(bridge)
    bridge.session.request.side_effect = [
        response(
            body={
                "result": {
                    **STATUS["result"],
                    "schedule": {"unverified": "SECRET"},
                    "diagnostics": {"accessToken": "SECRET"},
                }
            }
        )
    ]
    bridge.poll_status("TEST123")
    assert "SECRET" not in str(bridge.mqtt_client.publish.call_args_list)
