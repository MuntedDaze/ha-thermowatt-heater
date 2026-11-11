"""1.3.10: actual OFF code (Cmd 8) and the bounded pre-command status refresh.

Synthetic credentials, mocked HTTP and a mocked MQTT client only. No live
heater, cloud service or Home Assistant instance is contacted."""

import json
from types import SimpleNamespace

from jinja2 import Environment, StrictUndefined
import pytest
import requests

from conftest import STATUS, TOKENS, response
from test_cloud_and_commands import last_command, ready, status_messages

SERIAL = "TEST123"
TEMPLATES = Environment(undefined=StrictUndefined)
# What the owner's heater actually reported in T3 (1.3.9, 12 Nov 2026).
MANUAL_70 = {**STATUS["result"], "Cmd": "9", "T_SetPoint": "70", "WaterHeaterSts": "33"}
OFF_70 = {**STATUS["result"], "Cmd": "8", "T_SetPoint": "70", "WaterHeaterSts": "32"}


def body(result):
    return response(body={"result": dict(result)})


def set_status(bridge, cmd, setpoint=70, age=0):
    bridge.confirmed[SERIAL] = (
        bridge.monotonic() - age,
        {"T_Avg": 48, "T_SetPoint": setpoint, "Cmd": cmd, "WaterHeaterSts": 33},
    )
    bridge.last_status_attempt[SERIAL] = bridge.monotonic() - age


def stale(bridge, cmd, setpoint=70):
    """Last confirmed status from the previous ordinary poll, 25 minutes ago."""
    set_status(bridge, cmd, setpoint, age=1500)


def calls(bridge):
    return [
        (c.args[0], c.args[1].rsplit("/", 1)[-1]) for c in bridge.session.request.call_args_list
    ]


def commanded(factory, **options):
    bridge = factory(commands_enabled=True, **options)
    ready(bridge)
    return bridge


# --- Correct OFF interpretation -------------------------------------------------------


def test_manual_70_to_off_confirms_with_the_actual_cmd_8(factory, clock):
    bridge = commanded(factory)
    set_status(bridge, 9)
    bridge.session.request.side_effect = [response(204), body(OFF_70)]
    bridge.process_command((clock(), SERIAL, "MODE", "off"))
    assert calls(bridge) == [("POST", "off"), ("GET", "status")]
    assert bridge.session.request.call_args_list[0].kwargs["data"] == ""
    assert last_command(bridge)["result"] == "observed_in_status"
    assert last_command(bridge)["status_refresh"] == "not_needed"
    published = json.loads(status_messages(bridge)[-1])["result"]
    assert published["vendor_mode"] == "Off" and published["Cmd"] == "8"
    assert published["setpoint_valid"] is True and published["heating"] is None


def test_off_to_manual_70_from_actual_cmd_8_keeping_70(factory, clock):
    bridge = commanded(factory)
    set_status(bridge, 8, 70)
    bridge.session.request.side_effect = [response(204), body(MANUAL_70)]
    bridge.process_command((clock(), SERIAL, "MODE", "Manual:70"))
    write, read = bridge.session.request.call_args_list
    assert write.args[1].endswith("/manual") and write.kwargs["json"] == {"T_SetPoint": 70}
    assert last_command(bridge)["result"] == "observed_in_status"
    assert json.loads(status_messages(bridge)[-1])["result"]["vendor_mode"] == "Manual"


@pytest.mark.parametrize("off_code", [8, 16])
@pytest.mark.parametrize("observed", [40, 65, 20, 75, 69])
def test_usable_non_70_target_while_off_is_never_overwritten(factory, clock, off_code, observed):
    bridge = commanded(factory)
    set_status(bridge, off_code, observed)
    bridge.process_command((clock(), SERIAL, "MODE", "Manual:70"))
    bridge.session.request.assert_not_called()
    assert last_command(bridge)["result"] == "refused_target_mismatch"


@pytest.mark.parametrize("off_code", [8, 16])
@pytest.mark.parametrize("observed", [0, 5, 90])
def test_off_without_a_usable_target_may_resume_with_explicit_70(
    factory, clock, off_code, observed
):
    bridge = commanded(factory)
    set_status(bridge, off_code, observed)
    bridge.session.request.side_effect = [response(204), body(MANUAL_70)]
    bridge.process_command((clock(), SERIAL, "MODE", "Manual:70"))
    assert bridge.session.request.call_args_list[0].kwargs["json"] == {"T_SetPoint": 70}
    assert last_command(bridge)["result"] == "observed_in_status"


def test_cmd_16_remains_a_confirmed_off_for_compatibility(factory, clock):
    bridge = commanded(factory)
    set_status(bridge, 9)
    bridge.session.request.side_effect = [response(204), body({**OFF_70, "Cmd": "16"})]
    bridge.process_command((clock(), SERIAL, "MODE", "off"))
    assert last_command(bridge)["result"] == "observed_in_status"


@pytest.mark.parametrize("cmd", ["9", "17", "3", "65", "2", "64", "0"])
def test_off_is_not_confirmed_by_any_other_mode_code(factory, clock, cmd):
    bridge = commanded(factory)
    set_status(bridge, 9)
    bridge.session.request.side_effect = [response(204), body({**OFF_70, "Cmd": cmd})]
    bridge.process_command((clock(), SERIAL, "MODE", "off"))
    # 1.3.11: the previous mode (9) awaits a bounded follow-up; any other code
    # is neither old nor requested and ends the command (never success).
    expected = "awaiting_confirmation" if cmd == "9" else "unexpected_state_after_command"
    assert last_command(bridge)["result"] == expected
    assert bridge.session.request.call_count == 2  # never retried


@pytest.mark.parametrize("setpoint", ["0", "5", "90"])
def test_cmd_8_status_with_an_unusable_setpoint_is_still_published(factory, setpoint):
    bridge = factory()
    ready(bridge)
    bridge.session.request.side_effect = [body({**OFF_70, "T_SetPoint": setpoint})]
    bridge.poll_status(SERIAL)
    published = json.loads(status_messages(bridge)[-1])["result"]
    assert published["vendor_mode"] == "Off" and published["setpoint_valid"] is False


def test_home_assistant_entities_read_cmd_8_as_off(factory):
    bridge = factory()
    ready(bridge)
    bridge.publish_discovery(SERIAL, "Synthetic heater")
    configs = {
        c.args[0]: json.loads(c.args[1])
        for c in bridge.mqtt_client.publish.call_args_list
        if c.args[0].endswith("/config")
    }
    heater = configs[f"homeassistant/water_heater/{SERIAL}/config"]
    sensor = configs[f"homeassistant/sensor/{SERIAL}/vendor_mode/config"]
    assert heater["unique_id"] == f"thermowatt_{SERIAL}_v314"  # entity identity unchanged
    for result, ha_mode, vendor in ((OFF_70, "off", "Off"), (MANUAL_70, "performance", "Manual")):
        bridge.session.request.side_effect = [body(result)]
        bridge.poll_status(SERIAL)
        state = json.loads(status_messages(bridge)[-1])

        def render(template, state=state):
            return TEMPLATES.from_string(template).render(value_json=state)

        assert render(heater["mode_state_template"]) == ha_mode
        assert render(sensor["value_template"]) == vendor
        assert float(render(heater["temperature_state_template"])) == 70
        attributes = json.loads(render(sensor["json_attributes_template"]))
        # WaterHeaterSts is shown raw and still explicitly unverified.
        assert attributes["WaterHeaterSts"] == result["WaterHeaterSts"]
        assert attributes["heating_status_verified"] is False


# --- Fresh status: no extra read ---------------------------------------------------


def test_fresh_status_is_reused_without_a_refresh(factory, clock):
    bridge = commanded(factory)
    set_status(bridge, 9, age=59)
    bridge.session.request.side_effect = [response(204), body(OFF_70)]
    bridge.process_command((clock(), SERIAL, "MODE", "off"))
    assert calls(bridge) == [("POST", "off"), ("GET", "status")]
    assert bridge.usage.counts["command_refresh"] == 0


# --- Stale status: one bounded pre-command refresh -------------------------------------


@pytest.mark.parametrize(
    "start,payload,after",
    [(9, "off", OFF_70), (8, "Manual:70", MANUAL_70)],
)
def test_stale_status_one_refresh_then_command_and_confirmation(
    factory, clock, start, payload, after
):
    bridge = commanded(factory)
    stale(bridge, start)
    before = MANUAL_70 if start == 9 else OFF_70
    bridge.session.request.side_effect = [body(before), response(204), body(after)]
    bridge.process_command((clock(), SERIAL, "MODE", payload))
    assert [c[0] for c in calls(bridge)] == ["GET", "POST", "GET"]
    assert last_command(bridge)["result"] == "observed_in_status"
    assert last_command(bridge)["status_refresh"] == "refreshed"
    counts = bridge.usage.counts
    assert (counts["command_refresh"], counts["command"], counts["confirmation"]) == (1, 1, 1)
    assert counts["status"] == 0


def test_refresh_through_the_tick_counts_as_the_due_poll_without_a_duplicate(factory, clock):
    bridge = commanded(factory)
    stale(bridge, 9)
    bridge.next_poll = clock()  # an ordinary poll is due in the same tick
    bridge.next_background[SERIAL] = clock()
    bridge.commands.put((clock(), SERIAL, "MODE", "off"))
    bridge.session.request.side_effect = [body(MANUAL_70), response(204), body(OFF_70)]
    bridge.tick()
    assert [c[0] for c in calls(bridge)] == ["GET", "POST", "GET"]
    assert bridge.next_background[SERIAL] == clock() + bridge.poll_interval
    assert bridge.next_poll == clock() + 1800  # ordinary 30-minute cadence unchanged


def test_refresh_does_not_move_the_ordinary_poll_schedule(factory, clock):
    bridge = commanded(factory)
    bridge.session.request.side_effect = [body(MANUAL_70)]
    bridge.tick()  # ordinary poll
    deadline = bridge.next_poll
    clock.advance(600)
    bridge.commands.put((clock(), SERIAL, "MODE", "off"))
    bridge.session.request.side_effect = [body(MANUAL_70), response(204), body(OFF_70)]
    bridge.tick()
    assert bridge.session.request.call_count == 4
    assert bridge.next_poll == deadline
    assert last_command(bridge)["result"] == "observed_in_status"


@pytest.mark.parametrize(
    "refreshed,reason",
    [
        ({**MANUAL_70, "Cmd": "17", "T_SetPoint": "40"}, "refused_target_mismatch"),
        ({**MANUAL_70, "T_SetPoint": "65"}, "refused_target_mismatch"),
        ({**OFF_70, "T_SetPoint": "65"}, "refused_target_mismatch"),
        ({**MANUAL_70, "Cmd": "17"}, "refused_mode_mismatch"),  # Schedule at 70
        ({**MANUAL_70, "Cmd": "3"}, "refused_mode_mismatch"),  # Eco at 70
        ({**MANUAL_70, "Cmd": "65"}, "refused_mode_mismatch"),  # Holiday
        ({**MANUAL_70, "Cmd": "2"}, "refused_mode_mismatch"),  # unknown code
        (MANUAL_70, "already_in_requested_state"),
    ],
)
def test_resume_is_revalidated_against_the_refreshed_status(factory, clock, refreshed, reason):
    """The owner may have changed mode or target in the app since the last poll."""
    bridge = commanded(factory)
    stale(bridge, 8, 70)
    bridge.session.request.side_effect = [body(refreshed)]
    bridge.process_command((clock(), SERIAL, "MODE", "Manual:70"))
    assert calls(bridge) == [("GET", "status")]  # never a write
    assert last_command(bridge)["result"] == reason


@pytest.mark.parametrize(
    "refreshed,reason",
    [
        ({**MANUAL_70, "Cmd": "17"}, "refused_mode_mismatch"),  # owner chose Schedule
        ({**MANUAL_70, "Cmd": "3"}, "refused_mode_mismatch"),
        ({**MANUAL_70, "Cmd": "65"}, "refused_mode_mismatch"),
        ({**MANUAL_70, "Cmd": "2"}, "refused_mode_mismatch"),
        ({**MANUAL_70, "T_SetPoint": "60"}, "refused_target_mismatch"),  # owner's Manual 60
    ],
)
def test_park_is_revalidated_and_never_overrides_an_owner_choice(factory, clock, refreshed, reason):
    bridge = commanded(factory)
    stale(bridge, 9)
    bridge.session.request.side_effect = [body(refreshed)]
    bridge.process_command((clock(), SERIAL, "MODE", "off"))
    assert calls(bridge) == [("GET", "status")]  # never a write
    assert last_command(bridge)["result"] == reason


@pytest.mark.parametrize("cmd,setpoint", [(17, 70), (3, 70), (9, 60)])
def test_automation_park_with_fresh_status_also_requires_manual_70(factory, clock, cmd, setpoint):
    bridge = commanded(factory)
    set_status(bridge, cmd, setpoint)
    bridge.process_command((clock(), SERIAL, "MODE", "off"))
    bridge.session.request.assert_not_called()
    assert last_command(bridge)["result"].startswith("refused_")


def test_legacy_policy_keeps_the_1_3_9_off_and_resume_rules(factory, clock):
    bridge = commanded(factory, command_policy="legacy")
    set_status(bridge, 17, 40)
    bridge.session.request.side_effect = [response(204), body(OFF_70)]
    bridge.process_command((clock(), SERIAL, "MODE", "off"))
    assert last_command(bridge)["result"] == "observed_in_status"


def test_park_sees_heater_already_off_after_refresh_and_sends_nothing(factory, clock):
    bridge = commanded(factory)
    stale(bridge, 9)
    bridge.session.request.side_effect = [body(OFF_70)]
    bridge.process_command((clock(), SERIAL, "MODE", "off"))
    assert calls(bridge) == [("GET", "status")]
    assert last_command(bridge)["result"] == "already_in_requested_state"


def test_command_that_expires_during_a_slow_refresh_is_not_sent(factory, clock):
    bridge = commanded(factory)
    stale(bridge, 9)

    def slow(*args, **kwargs):
        clock.advance(50)  # within the HTTP timeout, but the command is now too old
        return body(MANUAL_70)

    bridge.session.request.side_effect = slow
    bridge.process_command((clock() - 29, SERIAL, "MODE", "off"))
    assert bridge.session.request.call_count == 1
    assert last_command(bridge)["result"] == "dropped_command_expired_during_refresh"


# --- Refresh failures: rejected safely, never executed ---------------------------------


@pytest.mark.parametrize(
    "failure,code",
    [
        (requests.Timeout(), "cloud_timeout"),
        (requests.ConnectionError(), "cloud_connection_error"),
        (response(503), "cloud_http_503"),
        (response(500), "cloud_http_500"),
        (response(body={"error": "Daily request limit exceeded"}), "cloud_daily_limit"),
        (response(body={}), "cloud_result_missing"),
        (body({**MANUAL_70, "T_SetPoint": "0"}), "status_temperature_out_of_range"),
    ],
)
def test_refresh_failure_rejects_the_command_with_poll_backoff(factory, clock, failure, code):
    bridge = commanded(factory)
    stale(bridge, 9)
    bridge.commands.put((clock(), SERIAL, "MODE", "off"))
    bridge.session.request.side_effect = [failure]
    bridge.tick()
    assert calls(bridge) == [("GET", "status")]  # no POST
    assert last_command(bridge)["result"] == "refused_status_refresh_failed"
    assert last_command(bridge)["status_refresh"] == "failed"
    assert last_command(bridge)["error"] == code
    # Treated like a failed status read: ordinary >= 60-minute backoff, persisted.
    assert bridge.next_poll >= clock() + 3600
    assert bridge.usage.cooldown_until == bridge.next_poll
    assert not bridge.confirmed and bridge.commands.empty()
    for _ in range(30):  # nothing is retried, even when the command is re-sent
        clock.advance(60)
        bridge.on_mqtt_message(
            None, None, SimpleNamespace(topic=f"P/{SERIAL}/CMD/MODE", payload=b"off", retain=False)
        )
        bridge.tick()
    assert bridge.session.request.call_count == 1


@pytest.mark.parametrize("status", [429, 403])
def test_refresh_quota_or_forbidden_keeps_the_persistent_lockout(factory, clock, module, status):
    bridge = commanded(factory)
    stale(bridge, 9)
    bridge.commands.put((clock(), SERIAL, "MODE", "off"))
    bridge.session.request.side_effect = [response(status)]
    bridge.tick()
    assert calls(bridge) == [("GET", "status")]
    assert bridge.guard.state["mode"] == "blocked"
    assert last_command(bridge)["result"] == "refused_status_refresh_failed"
    if status == 429:
        assert last_command(bridge)["error"] == "cloud_http_429"
        assert bridge.cloud_health == "quota_limited"
    restarted = factory(commands_enabled=True)
    restarted.tick()
    restarted.session.request.assert_not_called()


def test_refresh_authentication_failure_sends_no_command(factory, clock):
    bridge = commanded(factory)
    stale(bridge, 9)
    bridge.commands.put((clock(), SERIAL, "MODE", "off"))
    # 401 on the read, then the token refresh itself is refused.
    bridge.session.request.side_effect = [response(401), response(400)]
    bridge.tick()
    assert calls(bridge) == [("GET", "status"), ("POST", "refresh")]
    assert bridge.guard.state["mode"] == "blocked"
    assert last_command(bridge)["result"] == "refused_status_refresh_failed"


def test_refresh_after_an_expired_access_token_uses_the_existing_single_refresh(factory, clock):
    bridge = commanded(factory)
    stale(bridge, 9)
    bridge.session.request.side_effect = [
        response(401),
        response(body=TOKENS),
        body(MANUAL_70),
        response(204),
        body(OFF_70),
    ]
    bridge.process_command((clock(), SERIAL, "MODE", "off"))
    assert calls(bridge) == [
        ("GET", "status"),
        ("POST", "refresh"),
        ("GET", "status"),
        ("POST", "off"),
        ("GET", "status"),
    ]
    assert last_command(bridge)["result"] == "observed_in_status"


# --- Rejected before any cloud request --------------------------------------------------


@pytest.mark.parametrize(
    "setup,reason",
    [
        (lambda b, c: setattr(b.usage, "cooldown_until", c() + 600), "refused_cloud_backoff"),
        (lambda b, c: setattr(b, "cloud_health", "quota_limited"), "refused_cloud_quota_limited"),
        (lambda b, c: b.guard.state.update(mode="blocked"), "refused_auth_not_ready"),
        (lambda b, c: setattr(b.guard, "failed_storage", True), "refused_auth_not_ready"),
        (
            lambda b, c: b.last_status_attempt.__setitem__("TEST123", c() - 30),
            "refused_status_refresh_too_soon",
        ),
        (
            lambda b, c: b.command_refreshes.extend([c() - 60] * 24),
            "refused_status_refresh_limit",
        ),
    ],
)
def test_refresh_not_permitted_rejects_without_any_request(factory, clock, setup, reason):
    bridge = commanded(factory)
    stale(bridge, 9)
    setup(bridge, clock)
    bridge.process_command((clock(), SERIAL, "MODE", "off"))
    bridge.session.request.assert_not_called()
    assert last_command(bridge)["result"] == reason
    assert last_command(bridge)["status_refresh"] == "refused"


def test_refresh_budget_is_a_rolling_24_hours(factory, clock):
    bridge = commanded(factory)
    for _ in range(bridge.COMMAND_REFRESH_DAILY_LIMIT):
        stale(bridge, 9)
        bridge.session.request.side_effect = [body(OFF_70)]
        bridge.process_command((clock(), SERIAL, "MODE", "off"))
        assert last_command(bridge)["result"] == "already_in_requested_state"
        clock.advance(120)
    stale(bridge, 9)
    bridge.session.request.reset_mock(side_effect=True)
    bridge.process_command((clock(), SERIAL, "MODE", "off"))
    bridge.session.request.assert_not_called()
    assert last_command(bridge)["result"] == "refused_status_refresh_limit"
    clock.advance(86400)
    stale(bridge, 9)
    bridge.session.request.side_effect = [body(OFF_70)]
    bridge.process_command((clock(), SERIAL, "MODE", "off"))
    assert last_command(bridge)["result"] == "already_in_requested_state"


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("TEMP", "70"),
        ("TEMP", "40"),
        ("MODE", "Manual"),
        ("MODE", "Off"),
        ("MODE", "On"),
        ("MODE", "Eco"),
        ("MODE", "Auto"),
        ("MODE", "Holiday"),
        ("MODE", "Manual:65"),
        ("MODE", "off "),
        ("MODE", ""),
    ],
)
def test_off_policy_payloads_never_cause_a_refresh(factory, clock, kind, payload):
    bridge = commanded(factory)
    stale(bridge, 8)
    bridge.process_command((clock(), SERIAL, kind, payload))
    bridge.session.request.assert_not_called()
    assert last_command(bridge)["result"] == "refused_by_policy"
    assert last_command(bridge)["status_refresh"] is None


@pytest.mark.parametrize(
    "command,reason",
    [
        (lambda c: (c() - 31, SERIAL, "MODE", "off"), "dropped_command_older_than_30s"),
        (lambda c: (c(), "OTHER", "MODE", "off"), "dropped_unknown_device"),
    ],
)
def test_stale_or_unknown_commands_never_cause_a_refresh(factory, clock, command, reason):
    bridge = commanded(factory)
    stale(bridge, 9)
    bridge.process_command(command(clock))
    bridge.session.request.assert_not_called()
    assert last_command(bridge)["result"] == reason


def test_commands_disabled_by_default_never_refresh(factory, clock):
    bridge = factory()
    ready(bridge)
    stale(bridge, 9)
    for payload in (b"off", b"Manual:70"):
        bridge.on_mqtt_message(
            None, None, SimpleNamespace(topic=f"P/{SERIAL}/CMD/MODE", payload=payload, retain=False)
        )
    assert bridge.commands.empty()
    bridge.process_command((clock(), SERIAL, "MODE", "off"))
    bridge.session.request.assert_not_called()
    assert bridge.last_command is None


def test_mqtt_callback_only_queues_even_with_stale_status(factory, clock):
    bridge = commanded(factory)
    stale(bridge, 9)
    bridge.on_mqtt_message(
        None, None, SimpleNamespace(topic=f"P/{SERIAL}/CMD/MODE", payload=b"off", retain=False)
    )
    bridge.session.request.assert_not_called()
    assert bridge.commands.qsize() == 1


# --- Duplicates, replays and restart -----------------------------------------------------


def test_duplicate_commands_produce_one_write(factory, clock):
    bridge = commanded(factory)
    stale(bridge, 9)
    for _ in range(3):
        bridge.on_mqtt_message(
            None, None, SimpleNamespace(topic=f"P/{SERIAL}/CMD/MODE", payload=b"off", retain=False)
        )
    bridge.session.request.side_effect = [body(MANUAL_70), response(204), body(OFF_70)]
    bridge.tick()
    clock.advance(20)
    bridge.tick()
    clock.advance(20)
    bridge.tick()
    assert [c[0] for c in calls(bridge)] == ["GET", "POST", "GET"]
    assert last_command(bridge)["result"] in {
        "already_in_requested_state",
        "dropped_command_older_than_30s",
    }


def test_retained_command_replay_is_ignored(factory, clock):
    bridge = commanded(factory)
    stale(bridge, 9)
    bridge.on_mqtt_message(
        None, None, SimpleNamespace(topic=f"P/{SERIAL}/CMD/MODE", payload=b"off", retain=True)
    )
    assert bridge.commands.empty()


def test_restart_needs_discovery_before_any_command_and_keeps_the_guard(factory, clock):
    bridge = commanded(factory)
    guard = bridge.guard.path.read_bytes()
    restarted = factory(commands_enabled=True)
    assert restarted.guard.path.read_bytes() == guard
    assert restarted.confirmed == {} and restarted.command_refreshes == []
    restarted.process_command((clock(), SERIAL, "MODE", "off"))
    restarted.session.request.assert_not_called()
    assert restarted.last_command["result"] == "dropped_unknown_device"


def test_failure_clears_queued_commands_so_none_runs_later(factory, clock):
    bridge = commanded(factory)
    stale(bridge, 9)
    bridge.commands.put((clock(), SERIAL, "MODE", "off"))
    bridge.commands.put((clock(), SERIAL, "MODE", "Manual:70"))
    bridge.session.request.side_effect = [requests.Timeout()]
    bridge.tick()
    assert bridge.commands.empty()


# --- Accounting and diagnostics ------------------------------------------------------


def test_diagnostics_report_refresh_count_and_limit(factory, clock):
    bridge = commanded(factory)
    stale(bridge, 9)
    bridge.session.request.side_effect = [body(MANUAL_70), response(204), body(OFF_70)]
    bridge.process_command((clock(), SERIAL, "MODE", "off"))
    payload = json.loads(
        [
            c
            for c in bridge.mqtt_client.publish.call_args_list
            if c.args[0].endswith("/DIAGNOSTICS")
        ][-1].args[1]
    )
    assert payload["command_status_refreshes_24h"] == 1
    assert payload["command_status_refresh_limit_24h"] == 24
    assert payload["request_categories"]["command_refresh"] == 1
    assert payload["last_command"]["status_refresh"] == "refreshed"
    text = json.dumps(payload)
    for secret in ("SYNTHETIC_PASSWORD", "SYNTHETIC_ACCESS", "SYNTHETIC_REFRESH"):
        assert secret not in text


def test_older_request_ledger_is_upgraded_not_reset(factory, tmp_path):
    ledger = {
        "version": 1,
        "since": 5.0,
        "counts": {
            "password_login": 1,
            "token_refresh": 2,
            "discovery": 3,
            "status": 40,
            "command": 5,
            "confirmation": 5,
        },
        "complete": True,
        "cooldown_until": 0.0,
        "failures": 0,
        "last_error": None,
    }
    (tmp_path / "request_usage.json").write_text(json.dumps(ledger))
    bridge = factory()
    assert bridge.usage.complete is True and bridge.usage.since == 5.0
    assert bridge.usage.counts == {**ledger["counts"], "command_refresh": 0}
    saved = json.loads((tmp_path / "request_usage.json").read_text())
    assert saved["counts"]["status"] == 40 and saved["counts"]["command_refresh"] == 0


def test_legacy_policy_commands_use_the_same_bounded_refresh(factory, clock):
    bridge = commanded(factory, command_policy="legacy")
    stale(bridge, 9, 60)
    bridge.session.request.side_effect = [
        body(STATUS["result"]),
        response(204),
        body(STATUS["result"]),
    ]
    bridge.process_command((clock(), SERIAL, "MODE", "Manual"))
    assert [c[0] for c in calls(bridge)] == ["GET", "POST", "GET"]
    assert bridge.session.request.call_args_list[1].kwargs["json"] == {"T_SetPoint": 60}


def test_refresh_is_announced_before_its_status_so_it_is_never_read_as_an_outcome(factory, clock):
    """Order on MQTT: last_command=refreshing_status, then the pre-command
    STATUS, then the outcome. A consumer never sees that STATUS with an older
    or final outcome attached."""
    bridge = commanded(factory)
    stale(bridge, 9)
    bridge.session.request.side_effect = [body(OFF_70)]
    bridge.process_command((clock(), SERIAL, "MODE", "off"))
    sequence = []
    for call in bridge.mqtt_client.publish.call_args_list:
        if call.args[0].endswith("/DIAGNOSTICS"):
            last = json.loads(call.args[1])["last_command"]
            sequence.append(("diag", last and last["result"]))
        elif call.args[0].endswith("/STATUS"):
            sequence.append(("status", json.loads(call.args[1])["result"]["vendor_mode"]))
    first_status = sequence.index(("status", "Off"))
    assert ("diag", "refreshing_status") in sequence[:first_status]
    assert all(
        item == ("diag", "refreshing_status")
        for item in sequence[sequence.index(("diag", "refreshing_status")) : first_status]
    )
    assert sequence[first_status + 1 :][-1] == ("diag", "already_in_requested_state")
