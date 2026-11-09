"""Envelope diagnostics must identify shape only and retain 1.3.4 validation."""

from itertools import product

import pytest

from conftest import STATUS, response
from test_cloud_and_commands import ready, status_messages


@pytest.mark.parametrize("operation", ["status_poll", "device_discovery"])
@pytest.mark.parametrize(
    "body,code",
    [
        (None, "cloud_envelope_not_object"),
        ([], "cloud_envelope_not_object"),
        ("SENSITIVE_BODY", "cloud_envelope_not_object"),
        (17, "cloud_envelope_not_object"),
        (False, "cloud_envelope_not_object"),
        # Same first-failure precedence when multiple checks fail.
        ({"success": False, "error": "SENSITIVE_BODY"}, "cloud_success_false"),
        ({"error": "SENSITIVE_BODY"}, "cloud_error_nonempty"),
        ({"error": {"secret": "SENSITIVE_BODY"}}, "cloud_error_nonempty"),
        ({"error": ["SENSITIVE_BODY"]}, "cloud_error_nonempty"),
        ({"unrecognised": "SENSITIVE_BODY"}, "cloud_result_missing"),
        ({"result": None}, "cloud_result_wrong_type"),
        ({"result": []}, "cloud_result_wrong_type"),
        ({"result": "SENSITIVE_BODY"}, "cloud_result_wrong_type"),
        ({"result": 17}, "cloud_result_wrong_type"),
        ({"result": False}, "cloud_result_wrong_type"),
    ],
)
def test_fixed_envelope_codes_no_secrets_no_auth_changes_and_read_recovery(
    factory, clock, caplog, body, code, operation
):
    caplog.set_level("INFO")
    bridge = factory()
    ready(bridge)
    bridge.discovered = operation == "status_poll"
    original_guard = bridge.guard.path.read_bytes()
    caplog.clear()
    bridge.session.request.side_effect = [response(body=body)]
    bridge.tick()
    assert f"operation={operation} code={code}" in caplog.text
    assert "cloud_error_unclassified" not in caplog.text
    assert not status_messages(bridge) and not bridge.confirmed
    assert bridge.guard.path.read_bytes() == original_guard
    assert bridge.options["cloud_enabled"] is True
    assert bridge.options["commands_enabled"] is False
    assert bridge.session.request.call_count == 1
    # Ordinary cloud failure waits for the configured polling interval.
    bridge.tick()
    assert bridge.session.request.call_count == 1
    clock.advance(bridge.next_cloud - clock())
    recovery = [response(body=STATUS)]
    if operation == "device_discovery":
        recovery.insert(0, response(body={"result": {"termostati": [{"seriale": "TEST123"}]}}))
    bridge.session.request.side_effect = recovery
    bridge.tick()
    assert "cloud_cycle_recovered" in caplog.text
    assert bridge.availability["TEST123"] is True
    assert bridge.guard.path.read_bytes() == original_guard
    assert all(c.args[0] == "GET" for c in bridge.session.request.call_args_list)
    for secret in (
        "SENSITIVE_BODY",
        bridge.options["email"],
        bridge.options["password"],
        bridge.guard.state["access_token"],
        bridge.guard.state["refresh_token"],
        bridge.API_KEY,
    ):
        assert secret not in caplog.text
    # No traceback, raw exception, body or values are attached to log records.
    assert all(record.exc_info is None for record in caplog.records)


def test_acceptance_matches_released_1_3_4_envelope_predicate(module):
    """Differential regression against the old predicate, including falsey errors."""
    absent = object()
    scalars = [absent, None, False, True, 0, 1, "", "SYNTHETIC"]
    results = [absent, None, False, 17, [], "SYNTHETIC", {}, {"T_Avg": "48"}]
    for success, error, result in product(scalars, scalars + [[], {}], results):
        body = {
            key: value
            for key, value in (("success", success), ("error", error), ("result", result))
            if value is not absent
        }
        old_accepts = not (
            body.get("success") is False
            or body.get("error")
            or not isinstance(body.get("result"), dict)
        )
        try:
            actual = module.MyThermowattBridge._result(response(body=body))
        except module.CloudError:
            assert not old_accepts
        else:
            assert old_accepts
            assert actual is body["result"]


def test_invalid_json_keeps_existing_code_without_exception_contents(module):
    with pytest.raises(module.CloudError, match="^cloud_invalid_json$") as failure:
        module.MyThermowattBridge._result(response(body=ValueError("SENSITIVE_EXCEPTION")))
    assert "SENSITIVE_EXCEPTION" not in str(failure.value)
