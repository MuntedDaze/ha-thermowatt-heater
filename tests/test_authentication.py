import json
import logging
from unittest.mock import Mock

import pytest
import requests

from conftest import TOKENS, authenticate, response


def test_valid_login_and_restart_reuses_tokens(factory, module):
    bridge = factory()
    authenticate(bridge)
    stored = json.loads(bridge.guard.path.read_text())
    assert stored["access_token"] == "SYNTHETIC_ACCESS"
    restarted = factory()
    assert restarted.login()
    restarted.session.request.assert_not_called()
    assert restarted.config["device_uuid"] == bridge.config["device_uuid"]
    assert "access_token" not in json.loads(bridge.config_path.read_text())


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"error": "denied"},
        None,
        [],
        "html",
        {"result": None},
        {"result": []},
        {"result": {}},
        {"result": {"accessToken": "a"}},
        {"result": {"accessToken": "", "refreshToken": "b"}},
        {"result": {"accessToken": 123, "refreshToken": "b"}},
        {"result": {"accessToken": "a\r\nb", "refreshToken": "c"}},
        ValueError("SENSITIVE_RESPONSE_BODY"),
    ],
)
def test_unrecognised_login_blocks_across_restarts(factory, module, clock, body):
    bridge = factory()
    bridge.session.request.side_effect = [response(body=body)]
    with pytest.raises(module.AuthBlocked):
        bridge.login()
    assert bridge.session.request.call_count == 1
    for _ in range(4):
        restarted = factory()
        for _ in range(5):
            clock.advance()
            restarted.tick()
        restarted.session.request.assert_not_called()


@pytest.mark.parametrize("status", [201, 204, 301, 302, 400, 401, 403, 404, 408, 422, 429])
@pytest.mark.parametrize("action", ["login", "refresh"])
def test_rejected_auth_never_retries(factory, module, clock, status, action):
    bridge = factory()
    if action == "refresh":
        authenticate(bridge)
    bridge.session.request.side_effect = [response(status, {"secret": "SENSITIVE_BODY"})]
    with pytest.raises(module.AuthBlocked):
        getattr(bridge, "refresh_session" if action == "refresh" else "login")()
    assert bridge.session.request.call_count == 1
    for restarted in (bridge, factory()):
        for _ in range(10):
            clock.advance()
            restarted.tick()
        with pytest.raises(module.AuthBlocked):
            restarted.refresh_session()
    assert bridge.session.request.call_count == 1


@pytest.mark.parametrize(
    "failure",
    [
        requests.Timeout("secret"),
        requests.ConnectionError("secret"),
        response(500),
        response(502),
        response(503),
    ],
)
@pytest.mark.parametrize("action", ["login", "refresh"])
def test_transient_auth_budget_survives_restart(factory, module, clock, failure, action):
    bridge = factory()
    if action == "refresh":
        authenticate(bridge)
    for attempt in range(3):
        bridge.session.request.side_effect = [failure]
        with pytest.raises(module.CloudError):
            getattr(bridge, "refresh_session" if action == "refresh" else "login")()
        assert bridge.session.request.call_count == 1
        bridge = factory()
        if attempt < 2:
            with pytest.raises(module.CloudError, match="auth_retry_wait"):
                bridge.login()
            bridge.session.request.assert_not_called()
            clock.advance(60 if attempt == 0 else 300)
    assert bridge.guard.state["mode"] == "blocked"
    for _ in range(20):
        clock.advance()
        bridge.tick()
    bridge.session.request.assert_not_called()


def test_transient_recovers_without_password_fallback(factory, module, clock):
    bridge = factory()
    authenticate(bridge)
    bridge.session.request.side_effect = [requests.Timeout()]
    with pytest.raises(module.CloudError):
        bridge.refresh_session()
    restarted = factory()
    clock.advance()
    restarted.session.request.side_effect = [response(body=TOKENS)]
    restarted.login()
    assert restarted.session.request.call_args.args[1].endswith("/refresh")


def test_in_flight_interruption_blocks_even_with_credentials_changed(factory, module):
    bridge = factory()
    bridge.guard.begin("login")
    restarted = factory(password="changed")
    with pytest.raises(module.AuthBlocked):
        restarted.login()
    restarted.session.request.assert_not_called()
    assert restarted.guard.state["reason"] == "interrupted_auth"


def test_reset_generation_is_consumed_once_and_cannot_be_reused(factory, module):
    bridge = factory()
    bridge.session.request.side_effect = [response(401)]
    with pytest.raises(module.AuthBlocked):
        bridge.login()
    for generation in (0, 1):
        same = factory(auth_retry_generation=generation)
        with pytest.raises(module.AuthBlocked):
            same.login()
    permitted = factory(auth_retry_generation=2)
    permitted.session.request.side_effect = [response(403)]
    with pytest.raises(module.AuthBlocked):
        permitted.login()
    restarted = factory(auth_retry_generation=2)
    restarted.tick()
    restarted.session.request.assert_not_called()


def test_missing_corrupt_and_unwritable_guard_fail_closed(factory, module, monkeypatch):
    initial = factory(auth_retry_generation=0)
    initial.tick()
    initial.session.request.assert_not_called()
    initial.guard.path.write_text("broken-json")
    corrupt = factory()
    corrupt.tick()
    corrupt.session.request.assert_not_called()
    assert corrupt.guard.state["reason"] == "storage_invalid"
    permitted = factory(auth_retry_generation=2)

    def failed_write(*args):
        raise OSError("SENSITIVE_PATH")

    monkeypatch.setattr(module, "atomic_json", failed_write)
    with pytest.raises(module.AuthBlocked):
        permitted.login()
    permitted.session.request.assert_not_called()


@pytest.mark.parametrize(
    "value", [None, [], {"version": 1}, {"version": 9}, {"version": 1, "mode": "authorized"}]
)
def test_guard_schema_corruption_cannot_unlock(factory, value):
    bridge = factory()
    bridge.guard.path.write_text(json.dumps(value))
    restart = factory()
    restart.tick()
    restart.session.request.assert_not_called()


def test_account_change_requires_new_generation(factory):
    bridge = factory()
    authenticate(bridge)
    different = factory(email="other@example.invalid")
    different.tick()
    different.session.request.assert_not_called()
    assert different.guard.state["mode"] == "blocked"


def test_tls_error_is_not_retried(factory, module):
    bridge = factory()
    bridge.session.request.side_effect = [requests.exceptions.SSLError("SENSITIVE_TLS")]
    with pytest.raises(module.AuthBlocked):
        bridge.login()
    assert factory().guard.state["mode"] == "blocked"


def test_refresh_validates_response(factory, module):
    bridge = factory()
    authenticate(bridge)
    bridge.session.request.side_effect = [response(body={})]
    with pytest.raises(module.AuthBlocked):
        bridge.refresh_session()
    assert factory().guard.state["mode"] == "blocked"


def test_logs_never_include_secrets_or_response_bodies(factory, caplog, clock):
    caplog.set_level(logging.INFO)
    bridge = factory()
    bridge.session.request.side_effect = [
        response(body=TOKENS),
        requests.ConnectionError("SENSITIVE_BODY SYNTHETIC_PASSWORD"),
    ]
    bridge.tick()
    clock.advance()
    bridge.session.request.side_effect = [
        response(401),
        response(body=ValueError("SENSITIVE_BODY")),
    ]
    bridge.tick()
    for secret in (
        "SYNTHETIC_PASSWORD",
        "SYNTHETIC_ACCESS",
        "SYNTHETIC_REFRESH",
        "SENSITIVE_BODY",
        bridge.API_KEY,
        bridge.options["email"],
    ):
        assert secret not in caplog.text


def test_http_safety_and_auth_intent_is_persisted_before_request(factory):
    bridge = factory()

    def send(*args, **kwargs):
        assert json.loads(bridge.guard.path.read_text())["mode"] == "in_flight"
        assert kwargs["verify"] is True
        assert kwargs["timeout"] == (10, 20)
        assert kwargs["allow_redirects"] is False
        assert "Authorization" not in kwargs["headers"]
        return response(body=TOKENS)

    bridge.session.request.side_effect = send
    bridge.login()
    assert bridge.session.trust_env is False


def test_watchdog_style_run_stays_alive_after_auth_rejection(factory, clock):
    bridge = factory()
    bridge.session.request.side_effect = [response(401)]
    stop = Mock()
    stop.is_set.side_effect = [False] * 30 + [True]
    stop.wait.side_effect = lambda _: clock.advance()
    bridge.run(stop)
    assert bridge.session.request.call_count == 1
    assert stop.wait.call_count == 30


@pytest.mark.parametrize(
    "outcome",
    [
        response(body=TOKENS),
        response(401),
        response(403),
        response(429),
        response(500),
        response(503),
        response(body={}),
        response(body=ValueError("SENSITIVE_BODY")),
        requests.Timeout(),
        requests.ConnectionError(),
    ],
)
def test_single_attempt_diagnostic_always_locks_without_storing_tokens(
    factory, module, clock, outcome
):
    bridge = factory()
    bridge.session.request.side_effect = [outcome]
    try:
        bridge.diagnose_auth_once()
    except module.CloudError:
        pass
    assert bridge.session.request.call_count == 1
    assert bridge.session.request.call_args.args[1].endswith("/login")
    assert bridge.guard.state["mode"] == "blocked"
    assert bridge.guard.state["access_token"] is None
    assert bridge.guard.state["refresh_token"] is None
    bridge.mqtt_client.connect_async.assert_not_called()
    bridge.mqtt_client.publish.assert_not_called()
    restarted = factory()
    for _ in range(5):
        clock.advance()
        restarted.tick()
    restarted.session.request.assert_not_called()


def test_diagnostic_will_not_reuse_existing_session_or_retry_budget(factory, module):
    bridge = factory()
    authenticate(bridge)
    with pytest.raises(module.AuthBlocked):
        bridge.diagnose_auth_once()
    bridge.session.request.assert_not_called()


def test_failure_envelope_cannot_authenticate_even_with_tokens(factory, module):
    bridge = factory()
    bridge.session.request.side_effect = [response(body={**TOKENS, "success": False})]
    with pytest.raises(module.AuthBlocked):
        bridge.login()
    assert bridge.guard.state["mode"] == "blocked"


def test_refresh_keeps_existing_headers_without_password(factory):
    bridge = factory()
    authenticate(bridge)
    bridge.session.request.side_effect = [response(body=TOKENS)]
    bridge.refresh_session()
    call = bridge.session.request.call_args
    assert call.kwargs["headers"]["Authorization"] == "Bearer SYNTHETIC_ACCESS"
    assert call.kwargs["headers"]["x-api-key"] == bridge.API_KEY
    assert "password" not in call.kwargs["json"]
