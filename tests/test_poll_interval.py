"""Configurable ordinary polling; synthetic clocks, credentials and HTTP only."""

import json

import pytest
import requests

from conftest import STATUS, response
from test_cloud_and_commands import ready, status_messages


@pytest.mark.parametrize("minutes", [None, 1, 5, 30, 90, 1440])
def test_successful_polling_respects_interval_and_default(factory, clock, minutes):
    bridge = factory(**({} if minutes is None else {"poll_interval_minutes": minutes}))
    interval = (30 if minutes is None else minutes) * 60
    ready(bridge)
    original_guard = bridge.guard.path.read_bytes()
    bridge.session.request.side_effect = [response(body=STATUS) for _ in range(3)]
    bridge.tick()
    first = clock()
    assert bridge.poll_interval == interval
    assert len(status_messages(bridge)) == 1
    for cycle in (1, 2):
        # Walk the internal command cadence; it must not trigger ordinary reads.
        for elapsed in range(20, interval, 20):
            clock.now = first + (cycle - 1) * interval + elapsed
            bridge.tick()
            assert bridge.session.request.call_count == cycle
        clock.now = first + cycle * interval - 1
        bridge.tick()
        assert bridge.session.request.call_count == cycle
        clock.advance(1)
        bridge.tick()
        assert bridge.session.request.call_count == cycle + 1
    assert len(status_messages(bridge)) == 3
    assert bridge.guard.path.read_bytes() == original_guard
    assert all(c.args[0] == "GET" for c in bridge.session.request.call_args_list)


@pytest.mark.parametrize("discovery", [False, True])
@pytest.mark.parametrize(
    "failure",
    [
        response(body={"success": False}),
        response(body={"error": "SENSITIVE_BODY"}),
        response(body={}),
        response(body=ValueError("SENSITIVE_BODY")),
        response(400),
        response(500),
        response(503),
        requests.Timeout("SENSITIVE_BODY"),
        requests.ConnectionError("SENSITIVE_BODY"),
    ],
)
def test_ordinary_failures_wait_full_30_minutes_and_can_recover(
    factory, clock, discovery, failure, caplog
):
    caplog.set_level("INFO")
    bridge = factory()
    ready(bridge)
    original_guard = bridge.guard.path.read_bytes()
    bridge.discovered = not discovery
    bridge.session.request.side_effect = [failure, failure, failure]
    for attempt in range(3):
        bridge.tick()
        assert bridge.session.request.call_count == attempt + 1
        assert not status_messages(bridge) and not bridge.confirmed
        deadline = clock() + 1800
        assert bridge.next_cloud == deadline == bridge.next_poll
        # In particular, five-minute ticks must not cause another request.
        for _ in range(5):
            clock.advance(300)
            bridge.tick()
            assert bridge.session.request.call_count == attempt + 1
        clock.advance(299)
        bridge.tick()
        assert bridge.session.request.call_count == attempt + 1
        clock.advance(1)
    recovery = [response(body=STATUS)]
    if discovery:
        recovery.insert(0, response(body={"result": {"termostati": [{"seriale": "TEST123"}]}}))
    bridge.session.request.side_effect = recovery
    bridge.tick()
    assert bridge.availability["TEST123"] is True
    assert len(status_messages(bridge)) == 1
    assert "cloud_cycle_recovered" in caplog.text
    assert "SENSITIVE_BODY" not in caplog.text
    assert bridge.guard.path.read_bytes() == original_guard
    assert bridge.guard.state["generation"] == 1
    assert all(c.args[0] == "GET" for c in bridge.session.request.call_args_list)


def test_mqtt_reconnect_does_not_bypass_poll_deadline(factory, clock):
    bridge = factory()
    ready(bridge)
    bridge.session.request.side_effect = [response(body=STATUS)]
    bridge.tick()
    clock.advance(20)
    bridge.mqtt_reconnected.set()
    bridge.tick()
    assert bridge.discovered is False and not bridge.confirmed
    assert bridge.session.request.call_count == 1
    clock.advance(1779)
    bridge.tick()
    assert bridge.session.request.call_count == 1
    clock.advance(1)
    bridge.session.request.side_effect = [
        response(body={"result": {"termostati": [{"seriale": "TEST123"}]}}),
        response(body=STATUS),
    ]
    bridge.tick()
    assert bridge.session.request.call_count == 3


@pytest.mark.parametrize("refresh", [False, True])
def test_authentication_retry_timing_is_not_replaced_by_poll_interval(factory, clock, refresh):
    bridge = factory()
    if refresh:
        ready(bridge)
        bridge.session.request.side_effect = [response(401), requests.Timeout()]
    else:
        bridge.session.request.side_effect = [requests.Timeout()]
    bridge.tick()
    assert bridge.guard.state["mode"] == "retry"
    assert bridge.guard.state["next_retry"] == clock() + 60
    assert bridge.guard.state["attempts"] == 1
    assert bridge.next_cloud == clock() + 40  # Existing outer auth-error backoff.
    assert bridge.next_poll == 0
    restart = factory()
    assert restart.guard.state == bridge.guard.state
    restart.tick()
    restart.session.request.assert_not_called()


def test_fresh_command_keeps_existing_cadence_and_stale_command_still_rejected(factory, clock):
    bridge = factory(commands_enabled=True)  # Mocked instance, never a live heater.
    ready(bridge)
    bridge.session.request.side_effect = [response(body=STATUS)]
    bridge.tick()
    poll_deadline = bridge.next_poll
    clock.advance(20)
    bridge.commands.put((clock(), "TEST123", "MODE", "Manual"))
    bridge.session.request.side_effect = [response(204), response(body=STATUS)]
    bridge.tick()
    assert [c.args[0] for c in bridge.session.request.call_args_list] == ["GET", "POST", "GET"]
    assert bridge.next_poll == poll_deadline
    clock.advance(80)
    bridge.commands.put((clock(), "TEST123", "MODE", "Manual"))
    bridge.tick()
    assert bridge.session.request.call_count == 3  # Existing 60-second state-freshness guard.


@pytest.mark.parametrize(
    "cloud,commands", [(False, False), (True, False), (False, True), (True, True)]
)
@pytest.mark.parametrize("minutes", [None, 30, 60])
def test_saved_options_keep_credentials_flags_generation_and_custom_interval(
    module, tmp_path, factory, cloud, commands, minutes
):
    options = {
        "email": "synthetic@example.invalid",
        "password": "SYNTHETIC_PASSWORD",
        "cloud_enabled": cloud,
        "commands_enabled": commands,
        "auth_retry_generation": 7,
    }
    if minutes is not None:
        options["poll_interval_minutes"] = minutes
    path = tmp_path / "options.json"
    path.write_text(json.dumps(options))
    original = path.read_bytes()
    bridge = factory(**module.load_options(path))
    assert bridge.options == options
    assert bridge.poll_interval == (30 if minutes is None else minutes) * 60
    assert path.read_bytes() == original
    bridge.session.request.assert_not_called()


@pytest.mark.parametrize("minutes", [0, -1, 1441, True, False, 30.5, "30", None, []])
def test_invalid_poll_option_fails_before_startup(module, tmp_path, minutes):
    path = tmp_path / "options.json"
    path.write_text(json.dumps({"poll_interval_minutes": minutes}))
    with pytest.raises(ValueError):
        module.load_options(path)
