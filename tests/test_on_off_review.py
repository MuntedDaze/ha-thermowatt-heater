"""Mocked source-contract evidence; never proof of device power or retention."""

import json

import pytest

from conftest import STATUS, response
from test_cloud_and_commands import ready


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("MODE", "On"),
        ("MODE", "on"),
        ("MODE", "ON"),
        ("MODE", "Resume"),
        ("MODE", "resume"),
        ("POWER", "ON"),
    ],
)
def test_no_implicit_resume_command_or_invented_endpoint(factory, clock, kind, payload):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.process_command((clock(), "TEST123", kind, payload))
    bridge.session.request.assert_not_called()


def test_off_observation_does_not_manufacture_retained_mode_or_target(factory, clock):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.confirmed["TEST123"][1]["T_SetPoint"] = 70
    bridge.session.request.side_effect = [
        response(204),
        response(body={"result": {**STATUS["result"], "Cmd": "16", "T_SetPoint": "65"}}),
    ]
    bridge.process_command((clock(), "TEST123", "MODE", "off"))
    write, read = bridge.session.request.call_args_list
    assert write.args[0] == "POST" and write.args[1].endswith("/off")
    assert write.kwargs["data"] == "" and "json" not in write.kwargs
    assert read.args[0] == "GET" and read.args[1].endswith("/status")
    assert bridge.confirmed["TEST123"][1]["Cmd"] == 16
    assert bridge.confirmed["TEST123"][1]["T_SetPoint"] == 65
    bridge.session.request.reset_mock(side_effect=True)
    bridge.session.request.side_effect = [
        response(204),
        response(body={"result": {**STATUS["result"], "Cmd": "9", "T_SetPoint": "65"}}),
    ]
    bridge.process_command((clock(), "TEST123", "MODE", "Manual"))
    # Existing Manual writes the last observed target, not a saved pre-Off target.
    assert bridge.session.request.call_args_list[0].kwargs["json"] == {"T_SetPoint": 65}


def test_mqtt_discovery_does_not_advertise_separate_power_resume(factory):
    bridge = factory()
    bridge.publish_discovery("TEST123", "Synthetic heater")
    config = next(
        json.loads(call.args[1])
        for call in bridge.mqtt_client.publish.call_args_list
        if call.args[0].startswith("homeassistant/water_heater/")
        and call.args[0].endswith("/config")
    )
    assert "power_command_topic" not in config
    assert config["modes"] == ["off", "eco", "performance"]
    bridge.session.request.assert_not_called()
