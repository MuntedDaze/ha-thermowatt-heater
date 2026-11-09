"""Units, exact quota classification, private accounting and read-only MQTT."""

import json
from pathlib import Path

from jinja2 import Environment
import pytest
import yaml

from conftest import STATUS, TOKENS, response
from test_cloud_and_commands import ready
from thermowatt_read_only import poll_seconds


@pytest.mark.parametrize(
    "value,unit,expected",
    [
        (60, "seconds", 60),
        (7200, "seconds", 7200),
        (1, "minutes", 60),
        (120, "minutes", 7200),
        (30, "minutes", 1800),
    ],
)
def test_units_and_legacy_migration(factory, value, unit, expected):
    bridge = factory(poll_interval_minutes=value, poll_interval_unit=unit)
    assert bridge.poll_interval == expected
    assert poll_seconds({"poll_interval_minutes": value, "poll_interval_unit": unit}) == expected
    assert poll_seconds({"poll_interval_minutes": 17}) == 1020
    assert poll_seconds({}) == 1800


@pytest.mark.parametrize(
    "value,unit",
    [
        (59, "seconds"),
        (7201, "seconds"),
        (121, "minutes"),
        (0, "minutes"),
        (30, "hours"),
        (True, "seconds"),
        (1.5, "minutes"),
        ("60", "seconds"),
        (None, "minutes"),
    ],
)
def test_cross_field_validation_before_startup(module, tmp_path, value, unit):
    path = tmp_path / "options.json"
    path.write_text(json.dumps({"poll_interval_minutes": value, "poll_interval_unit": unit}))
    with pytest.raises(ValueError):
        module.load_options(path)


@pytest.mark.parametrize("success", [False, True, None])
def test_exact_daily_error_http_200_backoff_without_auth_reset(factory, clock, success, caplog):
    bridge = factory()
    ready(bridge)
    original = bridge.guard.path.read_bytes()
    bridge.session.request.side_effect = [
        response(
            body={
                "success": success,
                "error": "Daily request limit exceeded",
                "result": STATUS["result"],
            }
        )
    ]
    bridge.tick()
    assert bridge.last_error == "cloud_daily_limit"
    assert bridge.cloud_health == "quota_limited"
    assert bridge.next_cloud == clock() + 3600
    assert bridge.guard.path.read_bytes() == original
    assert "Daily request limit exceeded" not in caplog.text
    for _ in range(10):
        clock.advance(300)
        bridge.tick()
    assert bridge.session.request.call_count == 1
    restarted = factory()
    assert restarted.next_cloud == bridge.next_cloud
    restarted.tick()
    restarted.session.request.assert_not_called()
    assert restarted.last_error == "cloud_daily_limit"


@pytest.mark.parametrize(
    "error",
    [
        "daily request limit exceeded",
        "Daily request limit exceeded!",
        "prefix Daily request limit exceeded",
        {"message": "Daily request limit exceeded"},
        ["Daily request limit exceeded"],
        "Water heater not found",
    ],
)
def test_unrelated_or_near_match_error_remains_generic(factory, error):
    bridge = factory()
    ready(bridge)
    bridge.session.request.side_effect = [response(body={"success": False, "error": error})]
    bridge.tick()
    assert bridge.last_error == "cloud_success_false"
    assert bridge.cloud_health == "backoff"


def test_http_429_keeps_existing_operator_lock_across_restart(factory, clock):
    bridge = factory()
    ready(bridge)
    bridge.session.request.side_effect = [response(429)]
    bridge.tick()
    assert bridge.guard.state["reason"] == "cloud_http_429"
    assert bridge.cloud_health == "quota_limited"
    clock.advance(100000)
    restart = factory()
    restart.tick()
    restart.session.request.assert_not_called()
    assert restart.guard.state["reason"] == "cloud_http_429"


def test_private_usage_confirmation_categories_persist_without_identifiers(factory, clock):
    bridge = factory(commands_enabled=True)
    bridge.session.request.side_effect = [
        response(body=TOKENS),
        response(body={"result": {"termostati": [{"seriale": "TEST123"}]}}),
        response(body=STATUS),
    ]
    bridge.tick()
    clock.advance(20)
    bridge.commands.put((clock(), "TEST123", "MODE", "Manual"))
    bridge.session.request.side_effect = [response(204), response(body=STATUS)]
    bridge.tick()
    assert bridge.usage.counts == {
        "password_login": 1,
        "token_refresh": 0,
        "discovery": 1,
        "status": 1,
        "command": 1,
        "confirmation": 1,
    }
    assert bridge.usage.total == 5
    stored = bridge.usage.path.read_text()
    for secret in (
        bridge.options["email"],
        bridge.options["password"],
        *TOKENS["result"].values(),
        "TEST123",
        bridge.API_KEY,
    ):
        assert secret not in stored
    restart = factory()
    assert restart.usage.counts == bridge.usage.counts
    assert restart.usage.since == bridge.usage.since
    assert sum(restart.request_counts.values()) == 0
    assert restart.last_success == {}  # Retained data is never a new sample.
    if __import__("os").name == "posix":
        assert restart.usage.path.stat().st_mode & 0o777 == 0o600


def test_count_is_persisted_before_send_and_interruption_does_not_repeat_auth(factory, module):
    bridge = factory()

    def interrupted(*args, **kwargs):
        assert json.loads(bridge.usage.path.read_text())["counts"]["password_login"] == 1
        raise KeyboardInterrupt

    bridge.session.request.side_effect = interrupted
    with pytest.raises(KeyboardInterrupt):
        bridge.login()
    restart = factory()
    restart.tick()
    restart.session.request.assert_not_called()
    assert restart.usage.total == 1
    assert restart.guard.state["reason"] == "interrupted_auth"


def test_corrupt_or_unwritable_usage_never_unlocks_guard_or_leaks_content(
    factory, monkeypatch, caplog
):
    bridge = factory()
    ready(bridge)
    original_guard = bridge.guard.path.read_bytes()
    bridge.usage.path.write_text("SENSITIVE_BODY")
    restart = factory()
    assert restart.usage.complete is False
    assert restart.guard.path.read_bytes() == original_guard

    def failure(*args):
        raise OSError("SENSITIVE_PATH")

    restart.usage.writer = failure
    restart.session.request.side_effect = [response(body=STATUS)]
    restart.poll_status("TEST123")
    assert restart.usage.persistent is False
    assert restart.guard.path.read_bytes() == original_guard
    assert "SENSITIVE_BODY" not in caplog.text and "SENSITIVE_PATH" not in caplog.text


def diagnostic_messages(bridge):
    return [
        json.loads(c.args[1])
        for c in bridge.mqtt_client.publish.call_args_list
        if c.args[0].endswith("/DIAGNOSTICS")
    ]


def test_diagnostics_unknown_before_poll_then_age_health_and_safe_last_error(factory, clock):
    bridge = factory()
    ready(bridge)
    bridge.publish_diagnostics(force=True)
    assert diagnostic_messages(bridge)[-1]["last_successful_poll"] is None
    assert diagnostic_messages(bridge)[-1]["status_age_seconds"] is None
    bridge.session.request.side_effect = [response(body=STATUS)]
    bridge.tick()
    clock.advance(31)
    bridge.tick()
    message = diagnostic_messages(bridge)[-1]
    assert message["status_age_seconds"] == 31
    assert message["cloud_health"] == "ok"
    assert message["consumption_basis"] == "local_attempts_not_vendor_consumption"
    configs = {}
    bridge.publish_discovery("TEST123", "Synthetic heater")
    for call in bridge.mqtt_client.publish.call_args_list:
        if call.args[0].endswith("/config"):
            configs[call.args[0]] = json.loads(call.args[1])
    for key in (
        "last_successful_poll",
        "status_age_seconds",
        "cloud_health",
        "last_error",
        "request_attempts",
    ):
        config = configs[f"homeassistant/sensor/TEST123/{key}/config"]
        assert config["entity_category"] == "diagnostic"
        assert config["availability"] == [{"topic": "thermowatt/bridge/availability"}]
        assert "command_topic" not in config
        Environment().from_string(config["value_template"]).render(value_json=message)


def test_translation_uses_single_interval_number_and_clear_units():
    addon = Path(__file__).parents[1] / "thermowatt-heater"
    config = yaml.safe_load((addon / "config.yaml").read_text())
    translation = yaml.safe_load((addon / "translations/en.yaml").read_text())["configuration"]
    assert translation["poll_interval_minutes"]["name"] == "Polling interval"
    assert set(translation) == set(config["schema"])
    assert "poll_interval_value" not in config["schema"]


def test_diagnostic_publish_failure_cannot_lock_authentication(factory, caplog):
    bridge = factory()
    ready(bridge)
    original = bridge.guard.path.read_bytes()
    bridge.mqtt_client.publish.side_effect = RuntimeError("SENSITIVE_BODY")
    bridge.publish_diagnostics(force=True)
    assert bridge.guard.path.read_bytes() == original
    assert "mqtt_publish_failed" in caplog.text
    assert "SENSITIVE_BODY" not in caplog.text
    bridge.session.request.assert_not_called()


def test_persistent_attempts_include_refresh_and_read_replay(factory):
    bridge = factory()
    ready(bridge)
    bridge.session.request.side_effect = [
        response(401),
        response(body=TOKENS),
        response(body=STATUS),
    ]
    bridge.poll_status("TEST123")
    assert bridge.usage.counts["password_login"] == 1
    assert bridge.usage.counts["token_refresh"] == 1
    assert bridge.usage.counts["status"] == 2
    assert bridge.usage.total == 4


def test_json_quota_on_login_classifies_without_changing_original_auth_lock(factory, caplog):
    bridge = factory()
    bridge.session.request.side_effect = [
        response(body={"success": False, "error": "Daily request limit exceeded"})
    ]
    bridge.tick()
    assert bridge.last_error == "cloud_daily_limit"
    assert bridge.guard.state["reason"] == "auth_response_unrecognised"
    assert bridge.guard.state["mode"] == "blocked"
    assert "Daily request limit exceeded" not in caplog.text
    restart = factory()
    restart.tick()
    restart.session.request.assert_not_called()
