"""1.3.13: three-state guarded transitions, clock-aligned polling with reuse, no
immediate confirmation read and proactive token refresh. Production defaults
(proactive refresh on, no immediate read).

Synthetic credentials, mocked HTTP and a mocked MQTT client only."""

import json

import pytest

from conftest import STATUS, TOKENS, response
from test_cloud_and_commands import last_command, ready
from test_command_refresh_1_3_10 import MANUAL_70, OFF_70, SERIAL, body, calls, set_status, stale

MANUAL_45 = {**MANUAL_70, "T_SetPoint": "45"}


def bridge_1_3_13(factory, **options):
    bridge = factory(proactive_refresh=True, legacy_confirmation=False, **options)
    ready(bridge)
    bridge.token_obtained_at = bridge.clock()  # just logged in
    return bridge


def commanded(factory, **options):
    bridge = bridge_1_3_13(factory, commands_enabled=True, **options)
    bridge.next_poll = bridge.next_background[SERIAL] = bridge.clock() + 1800
    return bridge


def posts(bridge):
    return [c for c in calls(bridge) if c[0] == "POST"]


# --- three-state guarded transitions --------------------------------------------------------

TRANSITIONS = [
    # payload, prior (cmd, setpoint), endpoint, json body, confirming status
    ("Manual:45@off", (8, 70), "manual", {"T_SetPoint": 45}, MANUAL_45),
    ("Manual:70@off", (8, 45), "manual", {"T_SetPoint": 70}, MANUAL_70),
    ("Manual:45@70", (9, 70), "manual", {"T_SetPoint": 45}, MANUAL_45),
    ("Manual:70@45", (9, 45), "manual", {"T_SetPoint": 70}, MANUAL_70),
    ("off@45", (9, 45), "off", None, OFF_70),
    ("off@70", (9, 70), "off", None, OFF_70),
]


@pytest.mark.parametrize(("payload", "prior", "endpoint", "json_body", "confirm"), TRANSITIONS)
def test_each_transition_posts_once_from_its_stated_prior_state(
    factory, clock, payload, prior, endpoint, json_body, confirm
):
    bridge = commanded(factory)
    set_status(bridge, *prior)
    bridge.session.request.side_effect = [response(204)]
    bridge.process_command((clock(), SERIAL, "MODE", payload))
    assert calls(bridge) == [("POST", endpoint)]  # no immediate read (1.3.13)
    sent = bridge.session.request.call_args_list[0].kwargs
    assert sent.get("json") == json_body
    if json_body is None:
        assert sent["data"] == ""
    record = last_command(bridge)
    assert (record["payload"], record["result"]) == (payload, "submitted_awaiting_status")
    assert bridge.availability[SERIAL] is True  # still the last confirmed status
    clock.advance(60)
    bridge.session.request.side_effect = [body(confirm)]
    bridge.tick()
    assert last_command(bridge)["result"] == "observed_in_status"
    assert len(posts(bridge)) == 1


@pytest.mark.parametrize(
    ("payload", "observed", "reason"),
    [
        ("Manual:70@off", (9, 45), "refused_mode_mismatch"),  # owner set Manual 45
        ("Manual:45@off", (17, 45), "refused_mode_mismatch"),  # owner chose Schedule
        ("Manual:70@45", (9, 55), "refused_target_mismatch"),  # owner set 55
        ("Manual:70@45", (8, 45), "refused_mode_mismatch"),  # owner turned it OFF
        ("off@70", (9, 45), "refused_target_mismatch"),
        ("off@45", (3, 45), "refused_mode_mismatch"),  # Eco
        ("Manual:45@70", (65, 70), "refused_mode_mismatch"),  # Holiday
    ],
)
def test_owner_changes_are_never_overwritten(factory, clock, payload, observed, reason):
    bridge = commanded(factory)
    set_status(bridge, *observed)
    bridge.process_command((clock(), SERIAL, "MODE", payload))
    assert calls(bridge) == []
    assert last_command(bridge)["result"] == reason
    assert bridge.pending is None


@pytest.mark.parametrize(
    ("payload", "observed"),
    [("Manual:45@off", (9, 45)), ("Manual:70@45", (9, 70)), ("off@70", (8, 70))],
)
def test_target_already_active_needs_no_request(factory, clock, payload, observed):
    bridge = commanded(factory)
    set_status(bridge, *observed)
    bridge.process_command((clock(), SERIAL, "MODE", payload))
    assert calls(bridge) == []
    assert last_command(bridge)["result"] == "already_in_requested_state"


def test_stale_status_is_refreshed_once_and_the_prior_state_checked_on_it(factory, clock):
    bridge = commanded(factory)
    stale(bridge, 8, 70)  # the controller saw OFF 25 minutes ago
    bridge.session.request.side_effect = [body(MANUAL_45)]  # owner set Manual 45 since
    bridge.process_command((clock(), SERIAL, "MODE", "Manual:70@off"))
    assert calls(bridge) == [("GET", "status")]
    assert last_command(bridge)["result"] == "refused_mode_mismatch"


@pytest.mark.parametrize(
    "payload", ["Manual:50@off", "Manual:70@60", "off@off", "Manual:45", "off@", "Eco@off"]
)
def test_other_transition_forms_are_refused_before_any_request(factory, clock, payload):
    bridge = commanded(factory)
    set_status(bridge, 8, 70)
    bridge.process_command((clock(), SERIAL, "MODE", payload))
    assert calls(bridge) == []
    assert last_command(bridge)["result"] == "refused_by_policy"


def test_the_1_3_11_payloads_keep_their_meaning_for_the_installed_controller(factory, clock):
    bridge = commanded(factory)
    set_status(bridge, 9, 45)
    bridge.process_command((clock(), SERIAL, "MODE", "off"))  # off only from Manual 70
    assert calls(bridge) == [] and last_command(bridge)["result"] == "refused_target_mismatch"
    set_status(bridge, 8, 70)
    bridge.session.request.side_effect = [response(204)]
    bridge.process_command((clock(), SERIAL, "MODE", "Manual:70"))
    assert posts(bridge) == [("POST", "manual")]


def test_a_refused_transition_is_never_retried(factory, clock):
    bridge = commanded(factory)
    set_status(bridge, 9, 55)
    bridge.process_command((clock(), SERIAL, "MODE", "off@70"))
    for _ in range(10):
        clock.advance(20)
        bridge.tick()
    assert posts(bridge) == []


# --- confirmation without the immediate read ------------------------------------------------


def test_unconfirmed_then_not_confirmed_within_limit_with_two_reads_only(factory, clock):
    bridge = commanded(factory)
    set_status(bridge, 9, 70)
    bridge.session.request.side_effect = [response(204)]
    bridge.process_command((clock(), SERIAL, "MODE", "off@70"))
    posted = bridge.pending["posted_at"]
    for at, read in ((posted + 60, MANUAL_70), (posted + 300, MANUAL_70)):
        clock.now = at
        bridge.session.request.side_effect = [body(read)]
        bridge.tick()
    assert last_command(bridge)["result"] == "not_confirmed_within_limit"
    assert calls(bridge) == [("POST", "off"), ("GET", "status"), ("GET", "status")]


def test_a_command_now_costs_two_requests_not_three(factory, clock):
    bridge = commanded(factory)
    set_status(bridge, 8, 70)
    bridge.session.request.side_effect = [response(204)]
    bridge.process_command((clock(), SERIAL, "MODE", "Manual:45@off"))
    clock.advance(60)
    bridge.session.request.side_effect = [body(MANUAL_45)]
    bridge.tick()
    assert bridge.session.request.call_count == 2
    assert last_command(bridge)["result"] == "observed_in_status"


# --- clock-aligned polling ------------------------------------------------------------------


def test_polls_land_on_00_and_30_and_restart_does_not_shift_them(factory, clock):
    clock.now += 7 * 60 + 13  # start at hh:07:13
    bridge = bridge_1_3_13(factory)
    bridge.session.request.side_effect = [body(MANUAL_70)]
    bridge.tick()  # the startup read
    assert bridge.session.request.call_count == 1
    slot = bridge.next_poll
    assert slot % 1800 == 0 and slot - clock() == 1800 - (7 * 60 + 13)
    clock.now = slot
    bridge.token_obtained_at = clock()  # (token age is tested below)
    bridge.session.request.side_effect = [body(MANUAL_70)]
    bridge.tick()
    assert bridge.session.request.call_count == 2 and bridge.next_poll == slot + 1800


def test_a_due_poll_is_reused_after_a_recent_command_read_without_moving_the_schedule(
    factory, clock
):
    bridge = commanded(factory)
    slot = (clock() // 1800 + 1) * 1800
    bridge.next_poll = bridge.next_background[SERIAL] = slot
    clock.now = slot - 120  # 2 minutes before the slot: a park with its refresh
    bridge.token_obtained_at = clock()
    stale(bridge, 9, 70)
    bridge.session.request.side_effect = [body(MANUAL_70), response(204)]
    bridge.process_command((clock(), SERIAL, "MODE", "off@70"))
    clock.now = slot - 30  # the 60 s confirmation read
    bridge.session.request.side_effect = [body(OFF_70)]
    bridge.tick()
    assert last_command(bridge)["result"] == "observed_in_status"
    clock.now = slot
    bridge.tick()  # due, but the heater was read 30 s ago: reused, no request
    assert calls(bridge) == [("GET", "status"), ("POST", "off"), ("GET", "status")]
    assert bridge.next_background[SERIAL] == slot + 1800  # schedule kept


def test_reading_age_stays_bounded_by_interval_plus_reuse(factory, clock, module):
    assert module.POLL_REUSE_SECONDS <= 180  # the controller treats 35 min as stale
    bridge = bridge_1_3_13(factory)
    bridge.next_poll = bridge.next_background[SERIAL] = (clock() // 1800 + 1) * 1800
    clock.now = bridge.next_poll - module.POLL_REUSE_SECONDS + 1
    bridge.token_obtained_at = clock()
    bridge.session.request.side_effect = [body(MANUAL_70)]
    bridge.poll_status(SERIAL)
    last_read = clock()
    clock.now = bridge.next_poll
    bridge.tick()  # reused
    clock.now = bridge.next_poll
    bridge.token_obtained_at = clock()
    bridge.session.request.side_effect = [body(MANUAL_70)]
    bridge.tick()
    assert clock() - last_read <= 1800 + module.POLL_REUSE_SECONDS
    assert bridge.session.request.call_count == 2


# --- proactive token refresh ----------------------------------------------------------------


def test_an_old_token_is_refreshed_before_the_read_so_no_401_is_spent(factory, clock):
    bridge = bridge_1_3_13(factory)
    clock.advance(1800)
    bridge.session.request.side_effect = [response(body=TOKENS), body(MANUAL_70)]
    bridge.poll_status(SERIAL)
    assert calls(bridge) == [("POST", "refresh"), ("GET", "status")]
    assert bridge.request_counts["token_refresh"] == 1 and bridge.request_counts["status"] == 1
    assert bridge.guard.state["mode"] == "authorized"


def test_a_young_token_is_used_as_it_is(factory, clock):
    bridge = bridge_1_3_13(factory)
    clock.advance(600)
    bridge.session.request.side_effect = [body(MANUAL_70)]
    bridge.poll_status(SERIAL)
    assert calls(bridge) == [("GET", "status")]


def test_a_401_still_refreshes_once_when_the_token_dies_young(factory, clock):
    bridge = bridge_1_3_13(factory)
    clock.advance(900)
    bridge.session.request.side_effect = [response(401), response(body=TOKENS), body(MANUAL_70)]
    bridge.poll_status(SERIAL)
    assert calls(bridge) == [("GET", "status"), ("POST", "refresh"), ("GET", "status")]


def test_a_401_right_after_a_proactive_refresh_locks_as_before(factory, clock, module):
    bridge = bridge_1_3_13(factory)
    clock.advance(1800)
    bridge.session.request.side_effect = [response(body=TOKENS), response(401)]
    with pytest.raises(module.AuthBlocked):
        bridge.poll_status(SERIAL)
    assert bridge.guard.state["mode"] == "blocked"
    assert bridge.guard.state["access_token"] is None
    assert calls(bridge) == [("POST", "refresh"), ("GET", "status")]  # never a loop


def test_no_proactive_refresh_inside_the_guard_cooldown(factory, clock):
    bridge = bridge_1_3_13(factory)
    bridge.guard.state["next_retry"] = clock() + 100  # refreshed 200 s ago
    bridge.token_obtained_at = None
    bridge.session.request.side_effect = [body(MANUAL_70)]
    bridge.poll_status(SERIAL)
    assert calls(bridge) == [("GET", "status")]


def test_after_a_restart_the_token_age_comes_from_the_persisted_cooldown(factory, clock):
    bridge = bridge_1_3_13(factory)
    clock.advance(1800)
    bridge.session.request.side_effect = [response(body=TOKENS), body(MANUAL_70)]
    bridge.poll_status(SERIAL)  # refreshed at t
    clock.advance(600)
    restarted = factory(proactive_refresh=True, legacy_confirmation=False)
    assert restarted.token_obtained_at is None
    assert restarted._token_age() == pytest.approx(600)
    assert restarted._token_due_for_refresh() is False
    clock.advance(700)
    assert restarted._token_due_for_refresh() is True


def test_guard_file_schema_and_secrets_are_unchanged(factory, clock):
    bridge = bridge_1_3_13(factory)
    clock.advance(1800)
    bridge.session.request.side_effect = [response(body=TOKENS), body(MANUAL_70)]
    bridge.poll_status(SERIAL)
    state = json.loads(bridge.guard.path.read_text())
    assert set(state) == set(bridge.guard._empty())
    diagnostics = [
        c.args[1] for c in bridge.mqtt_client.publish.call_args_list if "DIAGNOSTICS" in c.args[0]
    ]
    for text in diagnostics:
        assert "SYNTHETIC_ACCESS" not in text and "SYNTHETIC_REFRESH" not in text


def test_a_day_of_30_minute_polls_costs_two_requests_each(factory, clock):
    bridge = bridge_1_3_13(factory)
    bridge.next_poll = bridge.next_background[SERIAL] = (clock() // 1800 + 1) * 1800
    bridge.session.request.side_effect = [
        item for _ in range(48) for item in (response(body=TOKENS), response(body=STATUS))
    ]
    for _ in range(48):
        clock.now = bridge.next_poll
        bridge.tick()
    assert bridge.request_counts["status"] == 48
    assert bridge.request_counts["token_refresh"] == 48
    assert bridge.request_counts["password_login"] == 1  # the test's initial login
    assert sum(bridge.request_counts.values()) - 1 == 96  # was 144 with the reactive 401


def test_diagnostics_advertise_the_transitions_for_the_controller(factory, clock):
    bridge = bridge_1_3_13(factory)
    bridge.publish_diagnostics(force=True)
    payload = json.loads(
        [c for c in bridge.mqtt_client.publish.call_args_list if "DIAGNOSTICS" in c.args[0]][
            -1
        ].args[1]
    )
    assert payload["command_transitions"] == sorted(t[0] for t in TRANSITIONS)
    assert payload["poll_schedule"] == "clock_aligned"
