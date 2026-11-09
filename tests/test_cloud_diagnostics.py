"""Fixed diagnostics and bounded refresh recovery; all services are mocked."""

import json

import pytest
import requests

from conftest import STATUS, TOKENS, authenticate, response
from test_cloud_and_commands import ready, status_messages


@pytest.mark.parametrize("operation", ["device_discovery", "status_poll"])
@pytest.mark.parametrize(
    "failure,code",
    [
        (requests.Timeout("SENSITIVE_EXCEPTION"), "cloud_timeout"),
        (requests.ConnectionError("SENSITIVE_EXCEPTION"), "cloud_connection_error"),
        (requests.RequestException("SENSITIVE_EXCEPTION"), "cloud_network_error"),
        (requests.exceptions.SSLError("SENSITIVE_EXCEPTION"), "cloud_tls_error"),
        (response(404), "cloud_http_404"),
        (response(503), "cloud_http_503"),
        (response(403), "cloud_http_403"),
        (response(429), "cloud_http_429"),
        (response(body=ValueError("SENSITIVE_BODY")), "cloud_invalid_json"),
        (response(body={"error": "SENSITIVE_BODY"}), "cloud_error_nonempty"),
        (response(body={"result": []}), "cloud_result_wrong_type"),
    ],
)
def test_tick_logs_safe_operation_and_failure(factory, operation, failure, code, caplog):
    bridge = factory()
    ready(bridge)
    bridge.discovered = operation == "status_poll"
    bridge.session.request.side_effect = [failure]
    bridge.tick()
    assert f"operation={operation} code={code}" in caplog.text
    assert "cloud_operation_failed" not in caplog.text
    assert not status_messages(bridge)
    assert not bridge.confirmed
    assert bridge.session.request.call_count == 1
    for secret in ("SENSITIVE_BODY", "SENSITIVE_EXCEPTION", *TOKENS["result"].values()):
        assert secret not in caplog.text


@pytest.mark.parametrize(
    "result,code",
    [
        ({}, "status_fields_missing"),
        ({**STATUS["result"], "T_Avg": "SENSITIVE_BODY"}, "status_values_non_numeric"),
        ({**STATUS["result"], "T_Avg": "nan"}, "status_values_non_finite"),
        ({**STATUS["result"], "T_SetPoint": 0}, "status_temperature_out_of_range"),
        ({**STATUS["result"], "Cmd": -1}, "status_mode_invalid"),
        ({**STATUS["result"], "WaterHeaterSts": 0.5}, "status_heater_state_invalid"),
    ],
)
def test_status_schema_failure_has_specific_safe_code(factory, result, code, caplog):
    bridge = factory()
    ready(bridge)
    bridge.session.request.side_effect = [response(body={"result": result})]
    bridge.tick()
    assert f"operation=status_poll code={code}" in caplog.text
    assert "SENSITIVE_BODY" not in caplog.text
    assert not status_messages(bridge)


def test_discovery_schema_and_private_storage_errors_are_distinct(
    factory, clock, module, monkeypatch, caplog
):
    bridge = factory()
    authenticate(bridge)
    bridge.session.request.side_effect = [response(body={"result": {"termostati": None}})]
    bridge.tick()
    assert "operation=device_discovery code=device_list_unrecognised" in caplog.text
    clock.advance()
    bridge.session.request.side_effect = [response(body={"result": {"termostati": []}})]

    def fail(*args):
        raise OSError("SENSITIVE_PATH")

    monkeypatch.setattr(module, "atomic_json", fail)
    bridge.tick()
    assert "operation=device_cache_storage code=private_storage_error" in caplog.text
    assert "SENSITIVE_PATH" not in caplog.text


def test_diagnostics_deduplicate_and_report_recovery(factory, clock, caplog):
    caplog.set_level("INFO")
    bridge = factory()
    ready(bridge)
    caplog.clear()
    bridge.session.request.side_effect = [response(503), response(503), response(body=STATUS)]
    bridge.tick()
    clock.advance()
    bridge.tick()
    assert caplog.text.count("operation=status_poll code=cloud_http_503") == 1
    clock.advance()
    bridge.tick()
    assert "cloud_cycle_recovered" in caplog.text
    assert bridge.failures == 0 and bridge.last_diagnostic is None
    assert bridge.availability["TEST123"] is True
    assert len(status_messages(bridge)) == 1
    assert all(call.args[0] == "GET" for call in bridge.session.request.call_args_list)


def test_password_login_refresh_and_reuse_logs_are_distinct(factory, caplog):
    caplog.set_level("INFO")
    bridge = factory()
    authenticate(bridge)
    bridge.session.request.side_effect = [
        response(401),
        response(body=TOKENS),
        response(body=STATUS),
    ]
    bridge.poll_status("TEST123")
    restart = factory()
    restart.login()
    restart.login()
    restart.session.request.assert_not_called()
    assert caplog.text.count("operation=password_login code=auth_login_accepted") == 1
    assert caplog.text.count("operation=token_refresh code=auth_refresh_accepted") == 1
    for secret in (
        "SYNTHETIC_PASSWORD",
        "SYNTHETIC_ACCESS",
        "SYNTHETIC_REFRESH",
        bridge.options["email"],
        bridge.API_KEY,
    ):
        assert secret not in caplog.text


@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize(
    "replay",
    [response(body=STATUS), response(503), requests.Timeout(), response(body=ValueError())],
)
def test_successful_refresh_cannot_loop_after_later_401(factory, clock, restart, replay, caplog):
    bridge = factory()
    ready(bridge)
    bridge.session.request.side_effect = [response(401), response(body=TOKENS), replay]
    bridge.tick()
    assert bridge.session.request.call_count == 3
    persisted = json.loads(bridge.guard.path.read_text())
    assert persisted["next_retry"] == clock() + bridge.guard.REFRESH_COOLDOWN
    assert persisted["generation"] == 1
    if restart:
        bridge = factory()
        assert bridge.guard.state["next_retry"] == persisted["next_retry"]
    clock.advance(100)
    bridge.session.request.reset_mock(side_effect=True)
    bridge.session.request.side_effect = [response(401)]
    bridge.tick()
    assert bridge.session.request.call_count == 1
    assert bridge.session.request.call_args.args[0] == "GET"
    assert "code=cloud_refresh_cooldown" in caplog.text
    assert bridge.guard.state["reason"] == "cloud_http_401"
    for instance in (bridge, factory()):
        for _ in range(10):
            clock.advance()
            instance.tick()
    assert bridge.session.request.call_count == 1
    assert bridge.guard.state["generation"] == 1


def test_two_devices_cannot_trigger_two_refreshes_in_one_tick(factory):
    bridge = factory()
    ready(bridge)
    bridge.active_devices.add("TEST456")
    bridge.session.request.side_effect = [
        response(401),
        response(body=TOKENS),
        response(body=STATUS),
        response(401),
    ]
    bridge.tick()
    assert [c.args[0] for c in bridge.session.request.call_args_list] == [
        "GET",
        "POST",
        "GET",
        "GET",
    ]
    assert bridge.guard.state["mode"] == "blocked"


def test_normal_reads_allowed_during_cooldown_and_later_refresh_can_recover(factory, clock):
    bridge = factory()
    ready(bridge)
    bridge.session.request.side_effect = [
        response(401),
        response(body=TOKENS),
        response(body=STATUS),
    ]
    bridge.poll_status("TEST123")
    deadline = bridge.guard.state["next_retry"]
    clock.advance(bridge.guard.REFRESH_COOLDOWN - 1)
    bridge.session.request.side_effect = [response(body=STATUS)]
    bridge.poll_status("TEST123")
    assert bridge.guard.state["next_retry"] == deadline
    clock.advance(1)
    bridge.session.request.side_effect = [
        response(401),
        response(body=TOKENS),
        response(body=STATUS),
    ]
    bridge.poll_status("TEST123")
    assert bridge.guard.state["mode"] == "authorized"
    assert bridge.guard.state["next_retry"] == clock() + bridge.guard.REFRESH_COOLDOWN


@pytest.mark.parametrize(
    "failure,code",
    [
        (requests.Timeout("SENSITIVE_EXCEPTION"), "auth_timeout"),
        (requests.ConnectionError("SENSITIVE_EXCEPTION"), "auth_connection_error"),
        (response(503), "auth_http_503"),
        (response(401), "auth_http_401"),
        (response(body={"result": {}}), "auth_response_unrecognised"),
    ],
)
@pytest.mark.parametrize("refresh", [False, True])
def test_auth_failure_identifies_actual_operation(factory, refresh, failure, code, caplog):
    bridge = factory()
    if refresh:
        ready(bridge)
        bridge.session.request.side_effect = [response(401), failure]
    else:
        bridge.session.request.side_effect = [failure]
    bridge.tick()
    operation = "token_refresh" if refresh else "password_login"
    assert f"operation={operation} code={code}" in caplog.text
    assert "SENSITIVE_EXCEPTION" not in caplog.text


def test_unrecognised_exception_codes_and_internal_values_are_not_logged(factory, module, caplog):
    bridge = factory()
    ready(bridge)
    bridge.session.request.side_effect = module.CloudError("SENSITIVE_BODY")
    bridge.tick()
    assert "code=cloud_error_unclassified" in caplog.text
    assert "SENSITIVE_BODY" not in caplog.text
    for code in ("auth_http_401 SENSITIVE_BODY", "cloud_http_503\nSENSITIVE_BODY", None):
        assert module.safe_diagnostic(code) == "cloud_error_unclassified"


@pytest.mark.parametrize("failure", [ValueError("SENSITIVE_VALUE"), TypeError("SENSITIVE_VALUE")])
def test_internal_value_errors_never_log_raw_exception(factory, failure, caplog):
    bridge = factory()
    ready(bridge)
    bridge.session.request.side_effect = failure
    bridge.tick()
    assert "operation=status_poll code=internal_value_error" in caplog.text
    assert "SENSITIVE_VALUE" not in caplog.text


def test_discovery_recovers_without_another_authentication(factory, clock, caplog):
    caplog.set_level("INFO")
    bridge = factory()
    authenticate(bridge)
    bridge.session.request.side_effect = [response(503)]
    bridge.tick()
    clock.advance()
    bridge.session.request.side_effect = [
        response(body={"result": {"termostati": [{"seriale": "TEST123"}]}}),
        response(body=STATUS),
    ]
    bridge.tick()
    assert bridge.discovered and bridge.availability["TEST123"] is True
    assert "cloud_cycle_recovered" in caplog.text
    assert all(call.args[0] == "GET" for call in bridge.session.request.call_args_list)


def test_refresh_timeout_recovers_after_restart_without_password_fallback(factory, clock, caplog):
    caplog.set_level("INFO")
    bridge = factory()
    ready(bridge)
    caplog.clear()
    bridge.session.request.side_effect = [response(401), requests.Timeout("SENSITIVE_EXCEPTION")]
    bridge.tick()
    assert "operation=token_refresh code=auth_timeout" in caplog.text
    restarted = factory()
    restarted.tick()
    restarted.session.request.assert_not_called()
    clock.advance(60)
    restarted.session.request.side_effect = [
        response(body=TOKENS),
        response(body={"result": {"termostati": [{"seriale": "TEST123"}]}}),
        response(body=STATUS),
    ]
    restarted.tick()
    assert restarted.guard.state["mode"] == "authorized"
    assert restarted.guard.state["next_retry"] == clock() + restarted.guard.REFRESH_COOLDOWN
    assert restarted.session.request.call_args_list[0].args[1].endswith("/refresh")
    assert not any(
        call.args[1].endswith("/login") for call in restarted.session.request.call_args_list
    )
    assert "auth_refresh_accepted" in caplog.text
    assert "auth_login_accepted" not in caplog.text


def test_command_failure_and_confirmation_read_have_distinct_operations(factory, clock, caplog):
    bridge = factory(commands_enabled=True)  # Synthetic isolated instance only.
    ready(bridge)
    bridge.session.request.side_effect = [response(body={"error": "SENSITIVE_BODY"})]
    bridge.commands.put((clock(), "TEST123", "MODE", "Manual"))
    bridge.tick()
    assert "operation=heater_command code=command_rejected" in caplog.text
    clock.advance()
    ready(bridge)
    bridge.session.request.side_effect = [response(204), response(503)]
    bridge.commands.put((clock(), "TEST123", "MODE", "Manual"))
    bridge.tick()
    assert "operation=status_poll code=cloud_http_503" in caplog.text
    assert "SENSITIVE_BODY" not in caplog.text
