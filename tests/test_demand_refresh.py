"""Demand reads stay in one worker and cannot bypass spacing or guards."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from conftest import STATUS, TOKENS, response
from test_cloud_and_commands import ready


def publish(bridge, serial="TEST123", payload=b"refresh", retained=False, topic=None):
    bridge.on_mqtt_message(
        None,
        None,
        SimpleNamespace(
            topic=topic or f"P/{serial}/refresh",
            payload=payload,
            retain=retained,
        ),
    )


def baseline(factory, clock, enabled=True):
    bridge = factory(on_demand_refresh_enabled=enabled)
    ready(bridge)
    bridge.session.request.side_effect = [response(body=STATUS)]
    bridge.tick()
    clock.advance(300)
    return bridge


def test_burst_coalesces_in_worker_and_suppresses_redundant_background(factory, clock):
    bridge = baseline(factory, clock)
    for _ in range(1000):
        publish(bridge)
    assert bridge.session.request.call_count == 1  # Callback did no HTTP.
    assert bridge.refresh_requested == {"TEST123"}
    bridge.session.request.side_effect = [response(body=STATUS)]
    bridge.tick()
    assert bridge.session.request.call_count == 2
    assert bridge.refresh_requested == set()
    assert bridge.next_poll == clock() + 1800
    clock.advance(1500)  # Former background deadline; demand replaced it.
    bridge.tick()
    assert bridge.session.request.call_count == 2
    clock.advance(300)
    bridge.session.request.side_effect = [response(body=STATUS)]
    bridge.tick()
    assert bridge.session.request.call_count == 3
    assert all(c.args[0] == "GET" for c in bridge.session.request.call_args_list)


def test_minimum_spacing_after_all_status_attempts_and_no_queued_retry(factory, clock):
    bridge = baseline(factory, clock)
    clock.advance(-1)
    publish(bridge)
    bridge.tick()
    assert not bridge.refresh_requested and bridge.session.request.call_count == 1
    clock.advance(1)
    publish(bridge)
    bridge.session.request.side_effect = [response(body=STATUS)]
    clock.advance(20)  # Existing worker/command cadence, no extra thread.
    bridge.tick()
    assert bridge.session.request.call_count == 2
    for _ in range(100):
        publish(bridge)
    assert not bridge.refresh_requested
    clock.advance(299)
    publish(bridge)
    bridge.tick()
    assert bridge.session.request.call_count == 2


@pytest.mark.parametrize(
    "payload,retained,topic",
    [
        (b"refresh", True, None),
        (b"", False, None),
        (b"off", False, None),
        (b"\xff", False, None),
        (b"refresh", False, "P/TEST123/refresh/extra"),
        (b"refresh", False, "wrong/TEST123/refresh"),
    ],
)
def test_retained_malformed_or_control_payload_cannot_trigger_read(
    factory, clock, payload, retained, topic
):
    bridge = baseline(factory, clock)
    publish(bridge, payload=payload, retained=retained, topic=topic)
    publish(bridge, serial="UNKNOWN")
    bridge.tick()
    assert not bridge.refresh_requested
    assert bridge.session.request.call_count == 1


@pytest.mark.parametrize(
    "state", ["disabled", "cloud_disabled", "mqtt_offline", "auth_locked", "history_incomplete"]
)
def test_read_permission_barriers(factory, clock, state):
    bridge = baseline(factory, clock, enabled=state != "disabled")
    if state == "cloud_disabled":
        bridge.options["cloud_enabled"] = False
    elif state == "mqtt_offline":
        bridge.mqtt_connected.clear()
    elif state == "auth_locked":
        bridge.guard.block("auth_http_401")
    elif state == "history_incomplete":
        bridge.usage.complete = False
    publish(bridge)
    bridge.tick()
    assert not bridge.refresh_requested
    assert bridge.session.request.call_count == 1


@pytest.mark.parametrize(
    "failure",
    [
        response(503),
        requests.Timeout(),
        response(body={"success": False, "error": "Daily request limit exceeded"}),
        response(429),
    ],
)
def test_demand_error_enters_original_cooldown_and_restart_cannot_bypass(factory, clock, failure):
    bridge = baseline(factory, clock)
    publish(bridge)
    bridge.session.request.side_effect = [failure]
    bridge.tick()
    deadline = bridge.next_cloud
    assert deadline == clock() + 3600
    for _ in range(20):
        publish(bridge)
        bridge.tick()
    assert bridge.session.request.call_count == 2
    assert not bridge.refresh_requested
    restart = factory(on_demand_refresh_enabled=True)
    assert restart.next_cloud == deadline
    publish(restart)
    restart.tick()
    restart.session.request.assert_not_called()
    assert not restart.refresh_requested


def test_multi_device_demand_does_not_poll_other_device_or_starve_its_background(factory, clock):
    bridge = factory(on_demand_refresh_enabled=True)
    ready(bridge)
    bridge.active_devices.add("TEST456")
    bridge.session.request.side_effect = [response(body=STATUS), response(body=STATUS)]
    bridge.tick()
    clock.advance(300)
    publish(bridge)
    bridge.session.request.side_effect = [response(body=STATUS)]
    bridge.tick()
    assert bridge.session.request.call_count == 3
    assert bridge.session.request.call_args.kwargs["headers"]["seriale"] == "TEST123"
    clock.advance(1500)
    bridge.session.request.side_effect = [response(body=STATUS)]
    bridge.tick()
    assert bridge.session.request.call_count == 4
    assert bridge.session.request.call_args.kwargs["headers"]["seriale"] == "TEST456"
    assert bridge.next_poll == clock() + 300


def test_demand_refresh_preserves_401_refresh_contract_without_heater_commands(factory, clock):
    bridge = baseline(factory, clock)
    publish(bridge)
    bridge.session.request.side_effect = [
        response(401),
        response(body=TOKENS),
        response(body=STATUS),
    ]
    bridge.tick()
    calls = bridge.session.request.call_args_list
    assert [c.args[0] for c in calls] == ["GET", "GET", "POST", "GET"]
    assert calls[2].args[1].endswith("/refresh")
    assert bridge.options["commands_enabled"] is False
    assert bridge.usage.counts["command"] == bridge.usage.counts["confirmation"] == 0
    assert bridge.guard.state["generation"] == 1


def test_default_does_not_subscribe_refresh_and_enabled_subscription_preserves_retain(factory):
    bridge = factory()
    bridge._subscribe("TEST123")
    assert [c.args[0] for c in bridge.mqtt_client.subscribe.call_args_list] == ["P/TEST123/CMD/#"]
    bridge.options["on_demand_refresh_enabled"] = True
    bridge._subscribe("TEST123")
    call = bridge.mqtt_client.subscribe.call_args_list[-1]
    assert call.args[0] == "P/TEST123/refresh"
    assert call.kwargs["options"].retainAsPublished is True


@pytest.mark.parametrize("value", ["true", 1, None, []])
def test_option_is_strictly_boolean(module, tmp_path, value):
    import json

    path = tmp_path / "options.json"
    path.write_text(json.dumps({"on_demand_refresh_enabled": value}))
    with pytest.raises(ValueError):
        module.load_options(path)


def test_expired_cooldown_does_not_reset_exponential_history_on_restart(factory, clock):
    bridge = baseline(factory, clock)
    publish(bridge)
    bridge.session.request.side_effect = [response(503)]
    bridge.tick()
    clock.now = bridge.next_cloud
    restart = factory(on_demand_refresh_enabled=True)
    assert restart.failures == 1
    restart.session.request.side_effect = [response(503)]  # Discovery fails first.
    restart.tick()
    assert restart.next_cloud == clock() + 7200
    assert restart.usage.failures == 2


@pytest.mark.parametrize(
    "error,code",
    [
        ("poll_interval_invalid", "poll_interval_invalid"),
        ("SENSITIVE_BODY", "configuration or private storage invalid"),
    ],
)
def test_startup_reports_only_safe_configuration_category(module, monkeypatch, caplog, error, code):
    stop = Mock()
    monkeypatch.setattr(module, "threading", SimpleNamespace(Event=lambda: stop))
    monkeypatch.setattr(module.signal, "signal", Mock())
    monkeypatch.setattr(module, "load_options", Mock(side_effect=ValueError(error)))
    module.main()
    assert code in caplog.text
    assert "SENSITIVE_BODY" not in caplog.text
    stop.wait.assert_called_once()
