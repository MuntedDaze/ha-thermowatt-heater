"""1.3.11: bounded command confirmation for a delayed cloud readback.

T3b (bridge 1.3.10): a stale-status `off` refreshed once, was POSTed, and the
official app then showed OFF, but the bridge's single immediate read still saw
the old mode and ended the command as `not_observed_in_immediate_status`.

Synthetic credentials, mocked HTTP and a mocked MQTT client only."""

import json
from types import SimpleNamespace

import pytest
import requests

from conftest import response
from test_cloud_and_commands import last_command, ready, status_messages
from test_command_refresh_1_3_10 import MANUAL_70, OFF_70, SERIAL, body, calls, stale

FOLLOWUPS = (60, 300)


def commanded(factory, **options):
    bridge = factory(commands_enabled=True, **options)
    ready(bridge)
    # Isolate command behaviour from the ordinary 30-minute poll.
    bridge.next_poll = bridge.clock() + 1800
    bridge.next_background[SERIAL] = bridge.clock() + 1800
    return bridge


def mqtt(bridge, payload):
    bridge.on_mqtt_message(
        None,
        None,
        SimpleNamespace(topic=f"P/{SERIAL}/CMD/MODE", payload=payload.encode(), retain=False),
    )


def diagnostics(bridge):
    return json.loads(
        [
            c
            for c in bridge.mqtt_client.publish.call_args_list
            if c.args[0].endswith("/DIAGNOSTICS")
        ][-1].args[1]
    )


def advance_to(bridge, clock, seconds_after_post, posted):
    clock.now = posted + seconds_after_post
    bridge.tick()


def posts(bridge):
    return [c for c in calls(bridge) if c[0] == "POST"]


def start_off(factory, clock, immediate):
    """Stale Manual 70 -> `off`: refresh, POST, immediate read ``immediate``."""
    bridge = commanded(factory)
    stale(bridge, 9)
    mqtt(bridge, "off")
    bridge.session.request.side_effect = [body(MANUAL_70), response(204), body(immediate)]
    bridge.tick()
    return bridge, clock()


# --- the T3b case: delayed readback ---------------------------------------------------


def test_t3b_delayed_off_is_awaiting_then_confirmed_by_the_first_follow_up(factory, clock):
    bridge, posted = start_off(factory, clock, MANUAL_70)
    assert calls(bridge) == [("GET", "status"), ("POST", "off"), ("GET", "status")]
    record = last_command(bridge)
    assert record["result"] == "awaiting_confirmation"  # not success, not failure
    assert record["observed_mode"] == "Manual" and record["status_reads"] == 1
    assert diagnostics(bridge)["command_confirmation_pending"] is True
    # Nothing more until the first follow-up is due.
    advance_to(bridge, clock, 40, posted)
    assert bridge.session.request.call_count == 3
    bridge.session.request.side_effect = [body(OFF_70)]
    advance_to(bridge, clock, 60, posted)
    assert calls(bridge)[3:] == [("GET", "status")]
    record = last_command(bridge)
    assert record["result"] == "observed_in_status" and record["observed_mode"] == "Off"
    assert record["status_reads"] == 2 and record["followups_done"] == 1
    assert diagnostics(bridge)["command_confirmation_pending"] is False
    assert json.loads(status_messages(bridge)[-1])["result"]["vendor_mode"] == "Off"
    assert len(posts(bridge)) == 1  # the POST is never repeated
    counts = bridge.usage.counts
    assert (counts["command_refresh"], counts["command"], counts["confirmation"]) == (1, 1, 2)


def test_slower_cloud_is_confirmed_by_the_second_follow_up(factory, clock):
    bridge, posted = start_off(factory, clock, MANUAL_70)
    bridge.session.request.side_effect = [body(MANUAL_70)]
    advance_to(bridge, clock, 60, posted)
    assert last_command(bridge)["result"] == "awaiting_confirmation"
    for seconds in range(80, 300, 20):  # no reads between the follow-ups
        advance_to(bridge, clock, seconds, posted)
    assert bridge.session.request.call_count == 4
    bridge.session.request.side_effect = [body(OFF_70)]
    advance_to(bridge, clock, 300, posted)
    assert last_command(bridge)["result"] == "observed_in_status"
    assert len(posts(bridge)) == 1


def test_no_confirmation_within_the_limit_is_a_terminal_fault_with_bounded_reads(factory, clock):
    bridge, posted = start_off(factory, clock, MANUAL_70)
    bridge.session.request.side_effect = [body(MANUAL_70), body(MANUAL_70)]
    for seconds in range(20, 900, 20):
        advance_to(bridge, clock, seconds, posted)
    assert calls(bridge) == [
        ("GET", "status"),  # pre-command refresh
        ("POST", "off"),
        ("GET", "status"),  # immediate
        ("GET", "status"),  # +60 s
        ("GET", "status"),  # +300 s
    ]
    record = last_command(bridge)
    assert record["result"] == "not_confirmed_within_limit"
    assert record["observed_mode"] == "Manual" and record["followups_done"] == 2
    assert diagnostics(bridge)["command_confirmation_pending"] is False


def test_immediate_read_already_showing_the_request_needs_no_follow_up(factory, clock):
    bridge, posted = start_off(factory, clock, OFF_70)
    assert last_command(bridge)["result"] == "observed_in_status"
    for seconds in range(20, 600, 20):
        advance_to(bridge, clock, seconds, posted)
    assert bridge.session.request.call_count == 3


def test_delayed_resume_confirms_only_at_manual_70(factory, clock):
    bridge = commanded(factory)
    stale(bridge, 8, 70)
    mqtt(bridge, "Manual:70")
    bridge.session.request.side_effect = [body(OFF_70), response(204), body(OFF_70)]
    bridge.tick()
    posted = clock()
    assert bridge.session.request.call_args_list[1].kwargs["json"] == {"T_SetPoint": 70}
    assert last_command(bridge)["result"] == "awaiting_confirmation"
    bridge.session.request.side_effect = [body(MANUAL_70)]
    advance_to(bridge, clock, 60, posted)
    assert last_command(bridge)["result"] == "observed_in_status"
    assert last_command(bridge)["observed_mode"] == "Manual"


@pytest.mark.parametrize(
    "later,result",
    [
        ({**MANUAL_70, "T_SetPoint": "65"}, "unexpected_state_after_command"),  # Manual, not 70
        ({**MANUAL_70, "Cmd": "17"}, "unexpected_state_after_command"),  # owner chose Schedule
        ({**MANUAL_70, "Cmd": "3"}, "unexpected_state_after_command"),
        ({**MANUAL_70, "Cmd": "2"}, "unexpected_state_after_command"),
    ],
)
def test_a_third_state_during_confirmation_stops_without_success(factory, clock, later, result):
    bridge = commanded(factory)
    stale(bridge, 8, 70)
    mqtt(bridge, "Manual:70")
    bridge.session.request.side_effect = [body(OFF_70), response(204), body(OFF_70)]
    bridge.tick()
    posted = clock()
    bridge.session.request.side_effect = [body(later)]
    advance_to(bridge, clock, 60, posted)
    assert last_command(bridge)["result"] == result
    for seconds in range(80, 600, 20):
        advance_to(bridge, clock, seconds, posted)
    assert bridge.session.request.call_count == 4  # no further follow-up, no POST
    assert len(posts(bridge)) == 1


def test_owner_turning_the_heater_off_meanwhile_is_indistinguishable_and_harmless(factory, clock):
    """If the owner sets exactly the requested state, that state is what was
    asked for; it is reported as observed (the controller re-inspects anyway)."""
    bridge, posted = start_off(factory, clock, MANUAL_70)
    bridge.session.request.side_effect = [body({**OFF_70, "Cmd": "16"})]
    advance_to(bridge, clock, 60, posted)
    assert last_command(bridge)["result"] == "observed_in_status"


# --- one uncertain command at a time ---------------------------------------------------


@pytest.mark.parametrize("payload", ["off", "off", "Manual:70", "Eco"])
def test_every_command_while_pending_is_refused_without_a_request(factory, clock, payload):
    bridge, posted = start_off(factory, clock, MANUAL_70)
    before = bridge.session.request.call_count
    clock.now = posted + 20
    mqtt(bridge, payload)
    bridge.tick()
    assert bridge.session.request.call_count == before
    diag = diagnostics(bridge)
    assert diag["refused_while_pending"]["result"] == "refused_confirmation_pending"
    # The pending record is never overwritten by the refusal.
    assert diag["last_command"]["result"] == "awaiting_confirmation"
    assert diag["last_command"]["payload"] == "off"


def test_mqtt_redelivery_of_the_same_command_never_posts_twice(factory, clock):
    bridge, posted = start_off(factory, clock, MANUAL_70)
    for seconds in (20, 40):
        clock.now = posted + seconds
        mqtt(bridge, "off")
        bridge.tick()
    bridge.session.request.side_effect = [body(OFF_70)]
    advance_to(bridge, clock, 60, posted)
    assert len(posts(bridge)) == 1
    assert last_command(bridge)["result"] == "observed_in_status"


def test_after_a_terminal_outcome_the_next_command_is_accepted_normally(factory, clock):
    bridge, posted = start_off(factory, clock, MANUAL_70)
    bridge.session.request.side_effect = [body(OFF_70)]
    advance_to(bridge, clock, 60, posted)
    clock.now = posted + 120  # status 60 s old: fresh for the next command
    mqtt(bridge, "Manual:70")
    bridge.session.request.side_effect = [response(204), body(MANUAL_70)]
    bridge.tick()
    assert [c[1] for c in posts(bridge)] == ["off", "manual"]
    assert last_command(bridge)["result"] == "observed_in_status"


# --- failures during confirmation -------------------------------------------------------


@pytest.mark.parametrize(
    "failure",
    [requests.Timeout(), requests.ConnectionError(), response(503), response(500)],
)
def test_failed_follow_up_keeps_waiting_and_the_next_follow_up_can_confirm(factory, clock, failure):
    bridge, posted = start_off(factory, clock, MANUAL_70)
    bridge.session.request.side_effect = [failure]
    advance_to(bridge, clock, 60, posted)
    assert bridge.pending is not None  # outcome still unknown, nothing assumed
    assert diagnostics(bridge)["command_confirmation_pending"] is True
    bridge.session.request.side_effect = [body(OFF_70)]
    for seconds in range(80, 320, 20):
        advance_to(bridge, clock, seconds, posted)
    assert last_command(bridge)["result"] == "observed_in_status"
    assert len(posts(bridge)) == 1


def test_failing_follow_ups_end_as_not_confirmed_at_the_deadline(factory, clock):
    bridge, posted = start_off(factory, clock, MANUAL_70)
    bridge.session.request.side_effect = [requests.Timeout(), requests.Timeout()]
    for seconds in range(20, 600, 20):
        clock.now = posted + seconds
        bridge.next_cloud = min(bridge.next_cloud, clock())  # let each follow-up run
        bridge.tick()
    record = last_command(bridge)
    assert record["result"] == "not_confirmed_within_limit"
    assert record["error"] == "cloud_timeout"
    assert len(posts(bridge)) == 1


@pytest.mark.parametrize("status", [403, 429])
def test_follow_up_lockout_keeps_the_guard_and_expires_without_requests(factory, clock, status):
    bridge, posted = start_off(factory, clock, MANUAL_70)
    bridge.session.request.side_effect = [response(status)]
    advance_to(bridge, clock, 60, posted)
    assert bridge.guard.state["mode"] == "blocked"
    count = bridge.session.request.call_count
    for seconds in range(80, 900, 20):
        advance_to(bridge, clock, seconds, posted)
    assert bridge.session.request.call_count == count
    assert last_command(bridge)["result"] == "not_confirmed_within_limit"


def test_immediate_read_failure_is_resolved_by_a_follow_up(factory, clock):
    bridge = commanded(factory)
    stale(bridge, 9)
    mqtt(bridge, "off")
    bridge.session.request.side_effect = [body(MANUAL_70), response(204), response(503)]
    bridge.tick()
    posted = clock()
    assert last_command(bridge)["result"] == "submitted_awaiting_status"
    bridge.session.request.side_effect = [body(OFF_70)]
    for seconds in range(20, 120, 20):
        advance_to(bridge, clock, seconds, posted)
    assert last_command(bridge)["result"] == "observed_in_status"
    assert len(posts(bridge)) == 1


@pytest.mark.parametrize("failure", [requests.Timeout(), response(500), response(502)])
def test_post_with_unknown_outcome_is_observed_never_resent(factory, clock, failure):
    """A POST timeout or server error may still have reached the heater."""
    bridge = commanded(factory)
    stale(bridge, 9)
    mqtt(bridge, "off")
    bridge.session.request.side_effect = [body(MANUAL_70), failure]
    bridge.tick()
    posted = clock()
    assert last_command(bridge)["result"] == "awaiting_confirmation"
    assert bridge.pending is not None
    bridge.session.request.side_effect = [body(OFF_70)]
    for seconds in range(20, 120, 20):
        advance_to(bridge, clock, seconds, posted)
    assert last_command(bridge)["result"] == "observed_in_status"
    assert len(posts(bridge)) == 1


def test_explicit_cloud_rejection_is_terminal_with_no_follow_up(factory, clock):
    bridge = commanded(factory)
    stale(bridge, 9)
    mqtt(bridge, "off")
    bridge.session.request.side_effect = [body(MANUAL_70), response(body={"success": False})]
    bridge.tick()
    assert last_command(bridge)["result"] == "rejected_by_cloud"
    assert bridge.pending is None
    count = bridge.session.request.call_count
    clock.advance(900)
    bridge.next_poll = clock() + 1800
    bridge.next_background[SERIAL] = clock() + 1800
    bridge.next_cloud = 0
    bridge.tick()
    assert bridge.session.request.call_count == count


# --- background polls, restart and storage ------------------------------------------------


def test_a_background_poll_in_the_window_is_evidence_without_a_duplicate_read(factory, clock):
    bridge, posted = start_off(factory, clock, MANUAL_70)
    clock.now = posted + 60
    bridge.next_poll = clock()  # the ordinary poll falls due with the follow-up
    bridge.next_background[SERIAL] = clock()
    bridge.next_cloud = 0
    bridge.session.request.side_effect = [body(OFF_70)]
    bridge.tick()
    assert bridge.session.request.call_count == 4  # one read served both
    assert last_command(bridge)["result"] == "observed_in_status"
    assert bridge.next_background[SERIAL] == bridge._next_slot()  # clock-aligned (1.3.13)


def test_restart_while_pending_never_resends_and_the_next_read_decides(factory, clock):
    bridge, posted = start_off(factory, clock, MANUAL_70)
    saved = json.loads(bridge.command_state_path.read_text())
    assert saved["pending"]["payload"] == "off"
    text = bridge.command_state_path.read_text()
    for secret in ("SYNTHETIC_PASSWORD", "SYNTHETIC_ACCESS", "SYNTHETIC_REFRESH", "synthetic@"):
        assert secret not in text
    restarted = factory(commands_enabled=True)
    assert restarted.pending is not None
    assert restarted.last_command["result"] == "awaiting_confirmation"
    clock.now = posted + 30
    restarted.mqtt_connected.set()
    mqtt(restarted, "off")  # a replayed or repeated command after restart
    restarted.session.request.side_effect = [
        response(body={"result": {"termostati": [{"seriale": SERIAL}]}}),
        body(OFF_70),
    ]
    restarted.tick()  # discovery + startup poll; the queued command is refused
    assert [c[0] for c in calls(restarted)] == ["GET", "GET"]
    assert restarted.last_command["result"] == "observed_in_status"
    assert restarted.refused_while_pending["result"] == "refused_confirmation_pending"
    assert restarted.pending is None


def test_restart_after_the_deadline_ends_not_confirmed_before_any_request(factory, clock):
    bridge, posted = start_off(factory, clock, MANUAL_70)
    clock.now = posted + 3600
    restarted = factory(commands_enabled=True)
    restarted._expire_pending()  # the first thing every tick does; needs no request
    restarted.session.request.assert_not_called()
    assert restarted.last_command["result"] == "not_confirmed_within_limit"
    assert restarted.pending is None
    # A later status read showing OFF does not revive the expired command.
    restarted.session.request.side_effect = [
        response(body={"result": {"termostati": [{"seriale": SERIAL}]}}),
        body(OFF_70),
    ]
    restarted.tick()
    assert restarted.last_command["result"] == "not_confirmed_within_limit"


def test_command_state_storage_failure_refuses_before_any_post(factory, clock, monkeypatch):
    bridge = commanded(factory)
    stale(bridge, 9)
    mqtt(bridge, "off")
    bridge.session.request.side_effect = [body(MANUAL_70)]

    def broken():
        raise OSError

    monkeypatch.setattr(bridge, "_save_command_state", broken)
    bridge.tick()
    assert calls(bridge) == [("GET", "status")]
    assert last_command(bridge)["result"] == "refused_command_state_unavailable"
    assert bridge.pending is None


@pytest.mark.parametrize("content", ["not json", '{"version": 9}', '{"version": 1, "pending": 5}'])
def test_invalid_command_state_is_ignored_safely(factory, tmp_path, content):
    (tmp_path / "command_state.json").write_text(content)
    bridge = factory(commands_enabled=True)
    assert bridge.pending is None and bridge.last_command is None


# --- budgets and diagnostics ------------------------------------------------------------


def test_worst_case_cloud_cost_per_command_is_five_requests(factory, clock):
    bridge, posted = start_off(factory, clock, MANUAL_70)
    bridge.session.request.side_effect = [body(MANUAL_70), body(MANUAL_70)]
    for seconds in range(20, 900, 20):
        advance_to(bridge, clock, seconds, posted)
    assert bridge.session.request.call_count == 5  # refresh, POST, 3 reads
    assert sum(bridge.usage.counts.values()) == 1 + 5  # plus the synthetic login


def test_diagnostics_announce_the_bounded_confirmation(factory, clock):
    bridge, posted = start_off(factory, clock, MANUAL_70)
    diag = diagnostics(bridge)
    assert diag["command_confirmation_followups_seconds"] == list(FOLLOWUPS)
    record = diag["last_command"]
    assert record["confirm_by"] > record["posted_at"]
    assert set(record) >= {"result", "status_refresh", "status_reads", "followups_done", "at"}
    text = json.dumps(diag)
    for secret in ("SYNTHETIC_PASSWORD", "SYNTHETIC_ACCESS", "SYNTHETIC_REFRESH"):
        assert secret not in text


def test_t3b_diagnostic_sequence_is_consistent(factory, clock):
    """Each published last_command moves only forward: submitting, submitted,
    awaiting, then one terminal outcome."""
    bridge, posted = start_off(factory, clock, MANUAL_70)
    bridge.session.request.side_effect = [body(OFF_70)]
    advance_to(bridge, clock, 60, posted)
    results = []
    for call in bridge.mqtt_client.publish.call_args_list:
        if call.args[0].endswith("/DIAGNOSTICS"):
            last = json.loads(call.args[1])["last_command"]
            if last and (not results or results[-1] != last["result"]):
                results.append(last["result"])
    assert results == [
        "refreshing_status",
        "submitting",
        "submitted_awaiting_status",
        "awaiting_confirmation",
        "observed_in_status",
    ]


def test_deadline_outcome_carries_only_an_error_from_this_command(factory, clock):
    bridge, posted = start_off(factory, clock, MANUAL_70)
    bridge.last_error = "cloud_http_503"  # an old, unrelated error
    bridge.pending["followups_done"] = 2  # no follow-up left; only the deadline
    clock.now = posted + 400
    bridge._expire_pending()
    assert last_command(bridge)["result"] == "not_confirmed_within_limit"
    assert "error" not in last_command(bridge)
