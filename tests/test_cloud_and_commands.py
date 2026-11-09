import json
from types import SimpleNamespace

import pytest
import requests

from conftest import STATUS, TOKENS, authenticate, response


def ready(bridge):
    authenticate(bridge)
    bridge.config["devices"] = {"TEST123": {"name": "Synthetic heater"}}
    bridge.active_devices = {"TEST123"}
    bridge.discovered = True
    bridge.confirmed["TEST123"] = (
        bridge.monotonic(),
        {
            "T_Avg": 48,
            "T_SetPoint": 60,
            "Cmd": 9,
            "WaterHeaterSts": 1,
        },
    )


def status_messages(bridge):
    return [
        call.args[1]
        for call in bridge.mqtt_client.publish.call_args_list
        if call.args[0].endswith("/STATUS")
    ]


def test_read_401_refreshes_once_and_replays_only_read(factory):
    bridge = factory()
    ready(bridge)
    bridge.session.request.side_effect = [
        response(401),
        response(body=TOKENS),
        response(body=STATUS),
    ]
    bridge.poll_status("TEST123")
    assert [c.args[0] for c in bridge.session.request.call_args_list] == ["GET", "POST", "GET"]
    assert bridge.session.request.call_args_list[1].args[1].endswith("/refresh")
    assert json.loads(status_messages(bridge)[0])["result"]["heating"] is None


def test_second_401_after_refresh_persistently_blocks(factory, module):
    bridge = factory()
    ready(bridge)
    bridge.session.request.side_effect = [response(401), response(body=TOKENS), response(401)]
    with pytest.raises(module.AuthBlocked):
        bridge.poll_status("TEST123")
    assert len(bridge.session.request.call_args_list) == 3
    restarted = factory()
    restarted.tick()
    restarted.session.request.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        response(400),
        response(404),
        response(500),
        response(503),
        requests.Timeout(),
        requests.ConnectionError(),
        response(body={}),
        response(body=ValueError()),
    ],
)
def test_poll_errors_backoff_without_login_or_state_publish(factory, clock, failure):
    bridge = factory()
    ready(bridge)
    bridge.session.request.side_effect = [failure, failure]
    bridge.tick()
    assert bridge.session.request.call_count == 1
    assert not status_messages(bridge)
    for _ in range(10):
        bridge.tick()
    assert bridge.session.request.call_count == 1
    clock.advance()
    bridge.tick()
    assert bridge.session.request.call_count == 2
    assert all(c.args[0] == "GET" for c in bridge.session.request.call_args_list)
    assert bridge.guard.state["mode"] == "authorized"


@pytest.mark.parametrize("status", [403, 429])
def test_cloud_rejection_locks_every_endpoint(factory, clock, status):
    bridge = factory()
    ready(bridge)
    bridge.session.request.side_effect = [response(status)]
    bridge.tick()
    for instance in (bridge, factory()):
        clock.advance()
        instance.tick()
    assert bridge.session.request.call_count == 1
    assert bridge.guard.state["mode"] == "blocked"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"result": {}},
        {"result": []},
        {"result": {**STATUS["result"], "Cmd": "-1"}},
        {"result": {**STATUS["result"], "T_Avg": "nan"}},
    ],
)
def test_bad_status_never_becomes_fake_state(factory, module, body):
    bridge = factory()
    ready(bridge)
    bridge.session.request.side_effect = [response(body=body)]
    with pytest.raises(module.CloudError):
        bridge.poll_status("TEST123")
    assert not status_messages(bridge)


def test_status_is_allowlisted_not_sensitive_body(factory):
    bridge = factory()
    ready(bridge)
    bridge.session.request.side_effect = [
        response(
            body={
                "token": "SECRET",
                "result": {
                    **STATUS["result"],
                    "password": "SECRET",
                    "accessToken": "SECRET",
                },
            }
        )
    ]
    bridge.poll_status("TEST123")
    assert "SECRET" not in str(bridge.mqtt_client.publish.call_args_list)


@pytest.mark.parametrize(
    "failure",
    [response(400), response(401), response(403), response(429), response(500), requests.Timeout()],
)
def test_failed_command_is_not_replayed_or_published_as_success(factory, clock, failure, caplog):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.session.request.side_effect = [failure]
    bridge.commands.put((clock(), "TEST123", "MODE", "off"))
    bridge.tick()
    assert bridge.session.request.call_count == 1
    assert bridge.session.request.call_args.args[0] == "POST"
    assert not status_messages(bridge)
    assert not bridge.confirmed
    assert "observed" not in caplog.text
    assert bridge.commands.empty()


def test_200_command_uses_actual_status_not_requested_value(factory, clock, caplog):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.session.request.side_effect = [
        response(body={}),
        response(body=STATUS),
    ]
    bridge.process_command((clock(), "TEST123", "TEMP", "65"))
    assert json.loads(status_messages(bridge)[0])["result"]["T_SetPoint"] == "60"
    assert "not confirmed" in caplog.text


def test_observed_command_confirmation_and_manual_preserves_setpoint(factory, clock, caplog):
    caplog.set_level("INFO")
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.session.request.side_effect = [response(204), response(body=STATUS)]
    bridge.process_command((clock(), "TEST123", "MODE", "Manual"))
    assert bridge.session.request.call_args_list[0].kwargs["json"] == {"T_SetPoint": 60}
    assert "Requested value observed" in caplog.text


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("TEMP", "nan"),
        ("TEMP", "inf"),
        ("TEMP", "19"),
        ("TEMP", "76"),
        ("TEMP", "60.5"),
        ("TEMP", "bad"),
        ("MODE", "typo"),
        ("MODE", "Holiday"),
    ],
)
def test_bad_commands_cannot_change_heater_or_schedules(factory, clock, kind, payload):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.process_command((clock(), "TEST123", kind, payload))
    bridge.session.request.assert_not_called()


def test_temperature_cannot_silently_change_mode(factory, clock):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.confirmed["TEST123"][1]["Cmd"] = 17
    bridge.process_command((clock(), "TEST123", "TEMP", "65"))
    bridge.session.request.assert_not_called()


@pytest.mark.parametrize("options", [{"cloud_enabled": False}, {"auth_retry_generation": 0}])
def test_default_disabled_and_generation_zero_do_not_touch_cloud(factory, options):
    bridge = factory(**options)
    bridge.tick()
    bridge.session.request.assert_not_called()


def test_mqtt_retained_disabled_unknown_stale_and_malformed_commands(factory, clock):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    for topic, retained, payload in [
        ("P/TEST123/CMD/MODE", True, b"off"),
        ("bad/TEST123/CMD/MODE", False, b"off"),
        ("P/TEST123/CMD/MODE/extra", False, b"off"),
        ("P/TEST123/CMD/MODE", False, b"\xff"),
    ]:
        bridge.on_mqtt_message(
            None, None, SimpleNamespace(topic=topic, payload=payload, retain=retained)
        )
    assert bridge.commands.empty()
    bridge.process_command((clock() - 31, "TEST123", "MODE", "off"))
    bridge.process_command((clock(), "UNKNOWN", "MODE", "off"))
    bridge.options["commands_enabled"] = False
    bridge.process_command((clock(), "TEST123", "MODE", "off"))
    bridge.session.request.assert_not_called()


def test_callback_only_queues_and_mqtt_disconnect_discards_commands(factory, clock):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.on_mqtt_message(
        None, None, SimpleNamespace(topic="P/TEST123/CMD/MODE", payload=b"off", retain=False)
    )
    bridge.session.request.assert_not_called()
    assert bridge.commands.qsize() == 1
    bridge.on_mqtt_disconnect(None, None, None, 1, None)
    bridge.tick()
    assert bridge.commands.empty()
    bridge.session.request.assert_not_called()


def test_discovery_preserves_ids_and_uses_confirmed_state(factory):
    bridge = factory()
    bridge.publish_discovery("TEST123", "Synthetic heater")
    heater, heating = [json.loads(c.args[1]) for c in bridge.mqtt_client.publish.call_args_list[:2]]
    assert heater["unique_id"] == "thermowatt_TEST123_v314"
    assert heater["optimistic"] is False
    assert heater["availability_mode"] == "all"
    assert "off" in heater["modes"]
    assert set(heater["modes"]) <= {
        "off",
        "eco",
        "electric",
        "gas",
        "heat_pump",
        "high_demand",
        "performance",
    }
    assert heating["unique_id"] == "thermowatt_TEST123_heating"
    assert heating["value_template"] == "{{ 'None' }}"
    assert "default(0)" not in str(heater)


def test_discovery_empty_or_bad_devices_never_triggers_login(factory, module):
    bridge = factory()
    authenticate(bridge)
    bridge.session.request.side_effect = [
        response(body={"result": {"termostati": []}}),
        response(body={"result": {"termostati": [{"seriale": "bad/#"}]}}),
    ]
    bridge.discover_devices()
    assert bridge.active_devices == set()
    with pytest.raises(module.CloudError):
        bridge.discover_devices()
    assert all(c.args[0] == "GET" for c in bridge.session.request.call_args_list)


@pytest.mark.parametrize("body", [{"success": False}, {"error": "SENSITIVE_BODY"}])
def test_http_200_command_failure_is_rejected_without_fake_state(factory, clock, body, caplog):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.session.request.side_effect = [response(body=body)]
    bridge.commands.put((clock(), "TEST123", "MODE", "off"))
    bridge.tick()
    assert bridge.session.request.call_count == 1
    assert not status_messages(bridge)
    assert "submitted" not in caplog.text
    assert "SENSITIVE_BODY" not in caplog.text


def test_invalid_command_ack_never_substitutes_requested_state(factory, clock):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.session.request.side_effect = [response(body=ValueError()), response(body=STATUS)]
    bridge.process_command((clock(), "TEST123", "MODE", "off"))
    assert json.loads(status_messages(bridge)[0])["result"]["Cmd"] == "9"


def test_explicit_failure_status_with_result_is_not_published(factory, module):
    bridge = factory()
    ready(bridge)
    bridge.session.request.side_effect = [response(body={**STATUS, "success": False})]
    with pytest.raises(module.CloudError):
        bridge.poll_status("TEST123")
    assert not status_messages(bridge)


@pytest.mark.parametrize(
    "kind,payload,endpoint,cmd,setpoint",
    [
        ("MODE", "Manual", "/manual", 9, 70),
        ("MODE", "Auto", "/auto", 17, 70),
        ("MODE", "Eco", "/eco", 3, 70),
        ("MODE", "off", "/off", 16, 70),
        ("TEMP", "65", "/manual", 9, 65),
    ],
)
def test_existing_command_contract_only_posts_once_then_reads_status(
    factory, clock, kind, payload, endpoint, cmd, setpoint
):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.confirmed["TEST123"][1]["T_SetPoint"] = 70
    bridge.session.request.side_effect = [
        response(204),
        response(
            body={
                "result": {
                    **STATUS["result"],
                    "Cmd": str(cmd),
                    "T_SetPoint": str(setpoint),
                }
            }
        ),
    ]
    bridge.process_command((clock(), "TEST123", kind, payload))
    write, read = bridge.session.request.call_args_list
    assert write.args[0] == "POST" and write.args[1].endswith(endpoint)
    assert read.args[0] == "GET" and read.args[1].endswith("/status")
    if endpoint == "/manual":
        assert write.kwargs["json"] == {"T_SetPoint": setpoint}
    else:
        assert write.kwargs["data"] == ""
        assert write.kwargs["headers"]["Content-Type"] == "text/plain"
    assert write.kwargs["headers"]["seriale"] == "TEST123"


@pytest.mark.parametrize(
    "kind,payload",
    [("MODE", "Manual"), ("MODE", "Auto"), ("MODE", "Eco"), ("MODE", "off"), ("TEMP", "65")],
)
def test_all_reviewed_commands_remain_disabled_by_default(factory, clock, kind, payload):
    bridge = factory()
    ready(bridge)
    bridge.process_command((clock(), "TEST123", kind, payload))
    bridge.session.request.assert_not_called()
