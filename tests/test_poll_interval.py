"""Configurable ordinary polling; synthetic clocks, credentials and HTTP only."""

import json

import pytest
import requests

from conftest import STATUS, TOKENS, response
from test_cloud_and_commands import ready, status_messages


@pytest.mark.parametrize("minutes", [None, 5, 30, 90, 120])
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
def test_ordinary_failures_wait_minimum_60_minutes_with_exponential_backoff_and_recovery(
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
        delay = 3600 * 2**attempt
        deadline = clock() + delay
        assert bridge.next_cloud == deadline == bridge.next_poll
        # In particular, five-minute ticks must not cause another request.
        for _ in range(delay // 300 - 1):
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
    assert bridge.next_poll == (clock() + 3600 if refresh else 0)
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
@pytest.mark.parametrize("retry", [None, 60, 180])
def test_saved_options_keep_credentials_flags_generation_and_custom_interval(
    module, tmp_path, factory, cloud, commands, minutes, retry
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
    if retry is not None:
        options["min_cloud_retry_minutes"] = retry
    path = tmp_path / "options.json"
    path.write_text(json.dumps(options))
    original = path.read_bytes()
    bridge = factory(**module.load_options(path))
    assert bridge.options == options
    assert bridge.poll_interval == (30 if minutes is None else minutes) * 60
    assert bridge.min_cloud_retry == (60 if retry is None else retry) * 60
    assert path.read_bytes() == original
    bridge.session.request.assert_not_called()


@pytest.mark.parametrize("minutes", [0, -1, 4, 121, True, False, 30.5, "30", None, []])
def test_invalid_poll_option_fails_before_startup(module, tmp_path, minutes):
    path = tmp_path / "options.json"
    path.write_text(json.dumps({"poll_interval_minutes": minutes}))
    with pytest.raises(ValueError):
        module.load_options(path)


@pytest.mark.parametrize("minutes", [0, 4, 1441, True, 60.5, "60", None, []])
def test_invalid_cloud_retry_option_fails_before_startup(module, tmp_path, minutes):
    path = tmp_path / "options.json"
    path.write_text(json.dumps({"min_cloud_retry_minutes": minutes}))
    with pytest.raises(ValueError):
        module.load_options(path)


@pytest.mark.parametrize("poll,retry", [(120, 5), (30, 60), (5, 1440)])
def test_retry_floor_and_bounded_backoff(factory, clock, poll, retry, caplog):
    bridge = factory(poll_interval_minutes=poll, min_cloud_retry_minutes=retry)
    ready(bridge)
    base = max(poll, retry) * 60
    for attempt in range(7):
        bridge.session.request.side_effect = [response(body={"success": False})]
        bridge.tick()
        expected = min(86400, base * 2 ** min(attempt, 4))
        assert bridge.next_cloud - clock() == expected
        assert expected >= poll * 60 and expected >= retry * 60
        assert f"backoff_seconds={expected}" in caplog.text
        clock.advance(expected)


def test_all_http_attempts_counted_including_auth_discovery_refresh_and_confirmation(
    factory, clock, caplog
):
    caplog.set_level("INFO")
    bridge = factory(commands_enabled=True)  # Mocked only.
    bridge.session.request.side_effect = [
        response(body=TOKENS),
        response(body={"result": {"termostati": [{"seriale": "TEST123"}]}}),
        response(401),
        response(body=TOKENS),
        response(body=STATUS),
    ]
    bridge.tick()
    clock.advance(20)
    bridge.commands.put((clock(), "TEST123", "MODE", "Manual"))
    bridge.session.request.side_effect = [response(204), response(body=STATUS)]
    bridge.tick()
    assert bridge.request_counts == {
        "password_login": 1,
        "token_refresh": 1,
        "discovery": 1,
        "status": 3,
        "command": 1,
    }
    assert sum(bridge.request_counts.values()) == bridge.session.request.call_count == 7
    assert "kind=status count_since_start=3 total_since_start=7" in caplog.text
    for secret in (
        bridge.options["email"],
        bridge.options["password"],
        *TOKENS["result"].values(),
        bridge.API_KEY,
    ):
        assert secret not in caplog.text
    old_guard = bridge.guard.path.read_bytes()
    restart = factory()
    assert sum(restart.request_counts.values()) == 0  # Explicit per-process accounting.
    assert restart.guard.path.read_bytes() == old_guard
    restart.session.request.assert_not_called()


def test_failed_attempt_counts_before_timeout_without_retries_inside_send(factory):
    bridge = factory()
    ready(bridge)
    bridge.session.request.side_effect = [requests.Timeout()]
    bridge.tick()
    assert bridge.request_counts["password_login"] == 1
    assert bridge.request_counts["status"] == 1
    assert bridge.session.request.call_count == 1


def test_refresh_transient_retries_on_auth_schedule_without_early_ordinary_read(factory, clock):
    bridge = factory()
    ready(bridge)
    bridge.session.request.side_effect = [response(401), requests.Timeout()]
    bridge.tick()
    poll_deadline = bridge.next_poll
    clock.advance(60)
    bridge.session.request.side_effect = [response(body=TOKENS)]
    bridge.tick()
    assert bridge.session.request.call_count == 3
    assert bridge.session.request.call_args.args[1].endswith("/refresh")
    assert bridge.guard.state["mode"] == "authorized"
    assert not status_messages(bridge)
    clock.advance(poll_deadline - clock() - 1)
    bridge.tick()
    assert bridge.session.request.call_count == 3
    clock.advance(1)
    bridge.session.request.side_effect = [response(body=STATUS)]
    bridge.tick()
    assert bridge.session.request.call_count == 4
    assert len(status_messages(bridge)) == 1
