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
    clock.advance(bridge.next_cloud - clock())
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
    bridge.confirmed["TEST123"][1].update(T_SetPoint=70)  # automation parks only Manual 70
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
    bridge = factory(commands_enabled=True, command_policy="legacy")
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
    bridge = factory(commands_enabled=True, command_policy="legacy")
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
    bridge.confirmed["TEST123"][1].update(T_SetPoint=70)  # automation parks only Manual 70
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
    bridge = factory(commands_enabled=True, command_policy="legacy")
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


# --- 1.3.9 guarded Manual and command outcome diagnostics -----------------------


def last_command(bridge):
    payloads = [
        json.loads(call.args[1])
        for call in bridge.mqtt_client.publish.call_args_list
        if call.args[0].endswith("/DIAGNOSTICS")
    ]
    return payloads[-1]["last_command"] if payloads else None


def test_guarded_manual_sends_explicit_70_only_when_observed_target_is_70(factory, clock):
    # From Schedule only under the legacy policy (1.3.10: automation resumes
    # only from OFF; see test_command_refresh_1_3_10.py).
    bridge = factory(commands_enabled=True, command_policy="legacy")
    ready(bridge)
    bridge.confirmed["TEST123"][1].update(T_SetPoint=70, Cmd=17)
    bridge.session.request.side_effect = [
        response(204),
        response(body={"result": {**STATUS["result"], "Cmd": "9", "T_SetPoint": "70"}}),
    ]
    bridge.process_command((clock(), "TEST123", "MODE", "Manual:70"))
    write, read = bridge.session.request.call_args_list
    assert write.args[0] == "POST" and write.args[1].endswith("/manual")
    assert write.kwargs["json"] == {"T_SetPoint": 70}
    assert last_command(bridge)["result"] == "observed_in_status"
    assert last_command(bridge)["payload"] == "Manual:70"


@pytest.mark.parametrize("observed", [65, 60, 69.5, 75])
def test_guarded_manual_refuses_any_other_observed_target_without_request(
    factory, clock, observed, caplog
):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.confirmed["TEST123"][1].update(T_SetPoint=observed, Cmd=17)
    bridge.process_command((clock(), "TEST123", "MODE", "Manual:70"))
    bridge.session.request.assert_not_called()
    assert last_command(bridge)["result"] == "refused_target_mismatch"
    assert "Guarded Manual refused" in caplog.text


@pytest.mark.parametrize("payload", ["Manual:65", "Manual:75", "Manual:", "manual:70"])
def test_only_the_exact_guarded_payload_is_accepted(factory, clock, payload):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.confirmed["TEST123"][1].update(T_SetPoint=70, Cmd=17)
    bridge.process_command((clock(), "TEST123", "MODE", payload))
    bridge.session.request.assert_not_called()
    assert last_command(bridge)["result"] == "refused_by_policy"
    assert last_command(bridge)["payload"] == "other"  # unknown payload text is never echoed


def test_stale_command_is_dropped_and_reported(factory, clock):
    # 1.3.10: stale STATUS no longer drops the command; it triggers at most one
    # bounded pre-command read (tests/test_command_refresh_1_3_10.py).
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.confirmed["TEST123"][1].update(T_SetPoint=70, Cmd=17)
    bridge.process_command((clock() - 31, "TEST123", "MODE", "Manual:70"))
    bridge.session.request.assert_not_called()
    assert last_command(bridge)["result"] == "dropped_command_older_than_30s"


def test_guarded_manual_remains_disabled_by_default_and_reports_nothing(factory, clock):
    bridge = factory()
    ready(bridge)
    bridge.confirmed["TEST123"][1].update(T_SetPoint=70, Cmd=17)
    bridge.process_command((clock(), "TEST123", "MODE", "Manual:70"))
    bridge.session.request.assert_not_called()
    assert bridge.last_command is None


def test_guarded_payload_passes_the_mqtt_callback_length_gate(factory, clock):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.mqtt_connected.set()
    bridge.on_mqtt_message(
        None, None, SimpleNamespace(topic="P/TEST123/CMD/MODE", payload=b"Manual:70", retain=False)
    )
    assert bridge.commands.get_nowait()[2:] == ("MODE", "Manual:70")


def test_unconfirmed_guarded_manual_is_reported_and_never_retried(factory, clock):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.confirmed["TEST123"][1].update(T_SetPoint=70, Cmd=8)
    bridge.session.request.side_effect = [
        response(204),
        response(body={"result": {**STATUS["result"], "Cmd": "8", "T_SetPoint": "70"}}),
    ]
    bridge.process_command((clock(), "TEST123", "MODE", "Manual:70"))
    assert bridge.session.request.call_count == 2
    assert last_command(bridge)["result"] == "not_observed_in_immediate_status"


def test_diagnostics_expose_commands_enabled_flag(factory, clock):
    bridge = factory(commands_enabled=False)
    ready(bridge)
    bridge.publish_diagnostics(force=True)
    payload = json.loads(
        [
            c
            for c in bridge.mqtt_client.publish.call_args_list
            if c.args[0].endswith("/DIAGNOSTICS")
        ][-1].args[1]
    )
    assert payload["commands_enabled"] is False and payload["last_command"] is None


# --- 1.3.9: software OFF as the parked state ------------------------------------------


@pytest.mark.parametrize("setpoint", ["0", "40", "70", "5", "90"])
def test_status_while_off_is_published_even_with_an_unusual_setpoint(factory, setpoint):
    bridge = factory()
    ready(bridge)
    body = {"result": {**STATUS["result"], "Cmd": "16", "T_SetPoint": setpoint}}
    bridge.session.request.side_effect = [response(body=body)]
    values = bridge.poll_status("TEST123")
    assert values["Cmd"] == 16
    published = json.loads(status_messages(bridge)[-1])["result"]
    assert published["vendor_mode"] == "Off"
    assert published["setpoint_valid"] is (20 <= float(setpoint) <= 75)


@pytest.mark.parametrize("cmd", ["9", "17", "3"])
def test_out_of_range_setpoint_outside_off_still_fails_the_poll(factory, module, cmd):
    bridge = factory()
    ready(bridge)
    body = {"result": {**STATUS["result"], "Cmd": cmd, "T_SetPoint": "0"}}
    bridge.session.request.side_effect = [response(body=body)]
    with pytest.raises(module.CloudError):
        bridge.poll_status("TEST123")


@pytest.mark.parametrize("observed", [0, 5, 90, 70])
def test_guarded_manual_from_off_sends_explicit_70_when_off_has_no_other_target(
    factory, clock, observed
):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.confirmed["TEST123"][1].update(T_SetPoint=observed, Cmd=16)
    bridge.session.request.side_effect = [
        response(204),
        response(body={"result": {**STATUS["result"], "Cmd": "9", "T_SetPoint": "70"}}),
    ]
    bridge.process_command((clock(), "TEST123", "MODE", "Manual:70"))
    write, read = bridge.session.request.call_args_list
    assert write.args[1].endswith("/manual") and write.kwargs["json"] == {"T_SetPoint": 70}
    assert last_command(bridge)["result"] == "observed_in_status"


def test_guarded_manual_from_schedule_with_other_target_is_still_refused(factory, clock):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.confirmed["TEST123"][1].update(T_SetPoint=40, Cmd=17)
    bridge.process_command((clock(), "TEST123", "MODE", "Manual:70"))
    bridge.session.request.assert_not_called()
    assert last_command(bridge)["result"] == "refused_target_mismatch"


def test_plain_manual_never_sends_an_invalid_setpoint_seen_while_off(factory, clock):
    bridge = factory(commands_enabled=True, command_policy="legacy")
    ready(bridge)
    bridge.confirmed["TEST123"][1].update(T_SetPoint=0, Cmd=16)
    bridge.process_command((clock(), "TEST123", "MODE", "Manual"))
    bridge.session.request.assert_not_called()
    assert last_command(bridge)["result"] == "refused_setpoint_unavailable"


def test_off_park_command_confirms_even_if_off_reports_an_unusual_setpoint(factory, clock):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.confirmed["TEST123"][1].update(T_SetPoint=70, Cmd=9)
    bridge.session.request.side_effect = [
        response(204),
        response(body={"result": {**STATUS["result"], "Cmd": "16", "T_SetPoint": "0"}}),
    ]
    bridge.process_command((clock(), "TEST123", "MODE", "off"))
    write, read = bridge.session.request.call_args_list
    assert write.args[1].endswith("/off") and write.kwargs["data"] == ""
    assert last_command(bridge)["result"] == "observed_in_status"
    assert bridge.cloud_health == "ok"


@pytest.mark.parametrize("observed", [40, 65, 20, 75])
def test_guarded_manual_never_silently_resets_a_usable_off_target(factory, clock, observed):
    """A usable target other than 70 while OFF may be the owner's setting: no
    request is sent and the refusal is visible (never a silent change to 70)."""
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.confirmed["TEST123"][1].update(T_SetPoint=observed, Cmd=16)
    bridge.process_command((clock(), "TEST123", "MODE", "Manual:70"))
    bridge.session.request.assert_not_called()
    assert last_command(bridge)["result"] == "refused_target_mismatch"


# --- 1.3.9: automation command policy (allowlist) -----------------------------------


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("TEMP", "65"),
        ("TEMP", "70"),
        ("TEMP", "40"),
        ("MODE", "Manual"),
        ("MODE", "Eco"),
        ("MODE", "Auto"),
        ("MODE", "Off"),
        ("MODE", "Holiday"),
        ("MODE", "on"),
        ("MODE", "On"),
        ("MODE", "Manual:65"),
        ("MODE", "manual:70"),
        ("MODE", "off "),
        ("MODE", ""),
        ("MODE", "Manual:70;off"),
    ],
)
@pytest.mark.parametrize("cmd", [9, 16, 17])
def test_automation_policy_blocks_every_unauthorised_command(factory, clock, kind, payload, cmd):
    bridge = factory(commands_enabled=True)  # default policy: automation
    ready(bridge)
    bridge.confirmed["TEST123"][1].update(T_SetPoint=70, Cmd=cmd)
    bridge.process_command((clock(), "TEST123", kind, payload))
    bridge.session.request.assert_not_called()
    assert last_command(bridge)["result"] == "refused_by_policy"


def test_unauthorised_commands_cannot_reach_the_heater_through_mqtt(factory, clock):
    """End to end through the MQTT callback and the worker loop: only the two
    automation commands ever produce an HTTP request."""
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.mqtt_connected.set()
    for topic, payload in [
        ("P/TEST123/CMD/TEMP", b"75"),
        ("P/TEST123/CMD/MODE", b"Eco"),
        ("P/TEST123/CMD/MODE", b"Auto"),
        ("P/TEST123/CMD/MODE", b"Manual"),
        ("P/TEST123/CMD/MODE", b"Holiday"),
    ]:
        bridge.on_mqtt_message(
            None, None, SimpleNamespace(topic=topic, payload=payload, retain=False)
        )
        bridge.confirmed["TEST123"] = (
            bridge.monotonic(),
            {**bridge.confirmed["TEST123"][1], "T_SetPoint": 70, "Cmd": 16},
        )
        bridge.process_command(bridge.commands.get_nowait())
        bridge.session.request.assert_not_called()
        assert last_command(bridge)["result"] == "refused_by_policy"
    bridge.session.request.side_effect = [
        response(204),
        response(body={"result": {**STATUS["result"], "Cmd": "9", "T_SetPoint": "70"}}),
    ]
    bridge.on_mqtt_message(
        None, None, SimpleNamespace(topic="P/TEST123/CMD/MODE", payload=b"Manual:70", retain=False)
    )
    bridge.process_command(bridge.commands.get_nowait())
    write, _ = bridge.session.request.call_args_list
    assert write.args[1].endswith("/manual") and write.kwargs["json"] == {"T_SetPoint": 70}


@pytest.mark.parametrize("cmd,payload,endpoint", [(16, "Manual:70", "/manual"), (9, "off", "/off")])
def test_automation_policy_allows_exactly_the_two_controller_commands(
    factory, clock, cmd, payload, endpoint
):
    bridge = factory(commands_enabled=True)
    ready(bridge)
    bridge.confirmed["TEST123"][1].update(T_SetPoint=70, Cmd=cmd)
    expected = {"/manual": "9", "/off": "16"}[endpoint]
    bridge.session.request.side_effect = [
        response(204),
        response(body={"result": {**STATUS["result"], "Cmd": expected, "T_SetPoint": "70"}}),
    ]
    bridge.process_command((clock(), "TEST123", "MODE", payload))
    write, read = bridge.session.request.call_args_list
    assert write.args[1].endswith(endpoint) and read.args[1].endswith("/status")
    assert last_command(bridge)["result"] == "observed_in_status"


def test_legacy_policy_must_be_chosen_explicitly_and_policy_is_validated(
    factory, clock, module, tmp_path
):
    bridge = factory(commands_enabled=True, command_policy="legacy")
    ready(bridge)
    bridge.session.request.side_effect = [response(204), response(body=STATUS)]
    bridge.process_command((clock(), "TEST123", "MODE", "Manual"))
    assert bridge.session.request.call_count == 2
    for bad in ("Legacy", "open", 1, None):
        path = tmp_path / "options.json"
        path.write_text(json.dumps({"command_policy": bad}))
        with pytest.raises(ValueError):
            module.load_options(path)
    path.write_text(json.dumps({}))
    assert module.load_options(path).get("command_policy", "automation") == "automation"


def test_policy_does_not_change_read_only_monitoring(factory):
    for policy in ("automation", "legacy"):
        bridge = factory(command_policy=policy)
        ready(bridge)
        for cmd in ("9", "16", "17", "3", "65"):
            body = {"result": {**STATUS["result"], "Cmd": cmd, "T_SetPoint": "70"}}
            bridge.session.request.side_effect = [response(body=body)]
            bridge.poll_status("TEST123")
            published = json.loads(status_messages(bridge)[-1])["result"]
            assert published["Cmd"] == cmd
        bridge.publish_diagnostics(force=True)
        diag = [
            c
            for c in bridge.mqtt_client.publish.call_args_list
            if c.args[0].endswith("/DIAGNOSTICS")
        ]
        assert json.loads(diag[-1].args[1])["command_policy"] == policy
