"""Actual worker scheduling of Smart (v3) plans with synthetic time, MQTT and cloud only.

0.18.0: Smart is the single normal polling mode (owner decision D2). These tests
were ported from the retired v1 plans; the scheduler properties are unchanged:
plans only queue, deadlines never slide later, a lost lease falls back to the
fixed schedule, bad plans are rejected, back-off is never shortened.
"""

from datetime import timedelta
import json
from types import SimpleNamespace
import importlib

import pytest
import requests

from conftest import STATUS, response
from test_cloud_and_commands import ready
from test_shadow_model import m
from test_simple_policy import MIN, MON, at
from thermowatt_polling import AdaptiveSchedule

adaptive = importlib.import_module(f"{m.__package__}.adaptive")
SERIAL = "TEST123"
SMART = {"cloud_polling": "smart"}


def hint(bridge, clock, delay=2400, **changes):
    plan = {
        "version": 3,
        "status_at": bridge.last_success[SERIAL],
        "issued_at": clock(),
        "delay_seconds": delay,
        "reason": "required_temperature",
        "owner_check_seconds": 5400,
        "polling_mode": "smart",
        **changes,
    }
    bridge.on_mqtt_message(
        None,
        None,
        SimpleNamespace(
            topic=f"P/{SERIAL}/poll_plan", payload=json.dumps(plan).encode(), retain=False
        ),
    )
    return plan


def setup(factory, clock, **options):
    b = factory(**{**SMART, **options})
    ready(b)
    b.session.request.side_effect = [response(body=STATUS)]
    b.tick()
    return b


def test_smart_plan_bounds():
    now = at(MON, 12)
    quiet = adaptive.smart_plan(now, now, stable_state="baseline", temperature_valid=True)
    assert quiet["delay_seconds"] == 5400 and quiet["owner_check_seconds"] == 5400
    night = adaptive.smart_plan(
        now, now, stable_state="off", temperature_valid=True, overnight=True
    )
    assert night["delay_seconds"] == 28800 and night["polling_mode"] == "smart"
    required = adaptive.smart_plan(now, now, temperature_valid=True)
    assert 900 <= required["delay_seconds"] <= 1800
    assert required["reason"] == "required_temperature"
    unknown = adaptive.smart_plan(now, now)
    assert unknown["delay_seconds"] == 900 and unknown["reason"] == "uncertain"
    imminent = adaptive.smart_plan(
        now, now, stable_state="baseline", temperature_valid=True, completion_at=now + 25 * MIN
    )
    assert imminent["delay_seconds"] == 1500 and imminent["reason"] == "before_decision"


def test_hints_only_queue_and_monotonic_deadline_does_not_slide(factory, clock):
    b = setup(factory, clock)
    anchor = clock()
    hint(b, clock)
    assert b.session.request.call_count == 1
    b.tick()
    assert b.next_poll == anchor + 2400
    for _ in range(1, 40):
        clock.advance(60)
        hint(b, clock)
        b.tick()
        assert b.session.request.call_count == 1
        assert b.next_poll == anchor + 2400
    clock.advance(60)
    b.session.request.side_effect = [response(body=STATUS)]
    b.tick()
    assert b.session.request.call_count == 2
    assert all(call.args[0] == "GET" for call in b.session.request.call_args_list)


def test_lost_controller_lease_falls_back_without_optimistic_delay(factory, clock):
    b = setup(factory, clock)
    anchor = clock()
    hint(b, clock)
    b.tick()
    clock.advance(181)
    b.tick()
    assert b.next_poll == anchor + 1800
    clock.advance(1800 - 181)
    b.session.request.side_effect = [response(body=STATUS)]
    b.tick()
    assert b.session.request.call_count == 2


@pytest.mark.parametrize(
    "change",
    [
        {"version": True},
        {"delay_seconds": 0},
        {"delay_seconds": 2401},
        {"delay_seconds": 899},
        {"status_at": 1},
        {"issued_at": 0},
        {"issued_at": float("nan")},
        {"reason": "bypass_auth"},
        {"extra": True},
        {"owner_check_seconds": 28801},
    ],
)
def test_bad_or_stale_plans_cannot_extend_status_or_authorise_http(factory, clock, change):
    b = setup(factory, clock)
    hint(b, clock, **change)
    b.tick()
    assert b.next_poll == clock() + 1800 and b.poll_schedule.counts["rejected"] == 1
    assert b.session.request.call_count == 1


def test_confirmation_replaces_the_anchor_and_rejects_old_plan(factory, clock):
    b = setup(factory, clock)
    old = hint(b, clock)
    b.tick()
    clock.advance(300)
    b.session.request.side_effect = [response(body=STATUS)]
    b.poll_status(SERIAL, category="confirmation")
    assert not b.poll_schedule.accept(SERIAL, json.dumps({**old, "issued_at": clock()}))
    b._adaptive_sync()
    assert b.next_poll == clock() + 1800


def test_backoff_never_shortened_by_hints(factory, clock):
    b = setup(factory, clock)
    clock.advance(1800)
    b.session.request.side_effect = requests.Timeout("SYNTHETIC")
    b.tick()
    assert b.cloud_health == "backoff"
    until = b.next_poll
    hint(b, clock, delay=900)
    for _ in range(10):
        clock.advance(60)
        b.tick()
    assert b.next_poll == until and b.session.request.call_count == 2


def test_restart_restores_counters_not_lease_or_cached_status(tmp_path):
    now = SimpleNamespace(wall=10000, mono=0)
    path = tmp_path / "poll.json"

    def writer(p, d):
        p.write_text(json.dumps(d), encoding="utf-8")

    def schedule():
        return AdaptiveSchedule(True, lambda: now.wall, lambda: now.mono, path, writer)

    s = schedule()
    s.observed(SERIAL, now.wall, 1800)
    assert s.accept(
        SERIAL,
        json.dumps(
            {
                "version": 3,
                "status_at": 10000,
                "issued_at": 10000,
                "delay_seconds": 2400,
                "reason": "required_temperature",
                "owner_check_seconds": 5400,
                "polling_mode": "smart",
            }
        ),
    )
    s.save()
    restored = schedule()
    assert restored.counts["accepted"] == 1 and restored.deadline(SERIAL) is None
    now.wall -= 3600
    now.mono += 60
    assert s.deadline(SERIAL) == 2400
    path.write_text("[]", encoding="utf-8")
    assert not schedule().active


def test_controller_plan_is_bounded_and_freshness_not_relaxed():
    now = at(MON, 12)
    p = adaptive.smart_plan(now, now - 32 * MIN, temperature_valid=True, decision_at=now)
    assert p["delay_seconds"] <= 2400
    assert adaptive.smart_plan(now, now + timedelta(seconds=1), temperature_valid=True) is None


def test_real_controller_follows_the_app_smart_choice_without_command_or_duplicate_http(
    tmp_path, monkeypatch
):
    """D2: one polling configuration. The controller has no polling setting; it
    sends Smart plans because the app reports Smart, and none otherwise."""
    from test_integration_0_9_0 import Rig, hobart

    rig = Rig(tmp_path, monkeypatch, hobart(MON, 22, 10))
    rig.bridge.options.update(SMART)
    rig.bridge.smart = rig.bridge.poll_schedule.enabled = True
    rig.run(hobart(MON + 1, 0, 15))
    assert rig.bridge.poll_schedule.counts["accepted"] > 60
    assert rig.bridge.poll_schedule.counts["rejected"] == 0
    assert rig.commands() == [] and rig.posts == []
    assert rig.runtime.values["adaptive_polling_status"].startswith("adaptive:")


def test_controller_sends_no_plan_when_the_app_is_not_on_smart(tmp_path, monkeypatch):
    from test_integration_0_9_0 import Rig, hobart

    rig = Rig(tmp_path, monkeypatch, hobart(MON, 22, 10))
    rig.run(hobart(MON, 23, 30))
    assert rig.bridge.poll_schedule.counts["accepted"] == 0
    assert rig.bridge.poll_schedule.counts["rejected"] == 0
    assert not rig.bridge.poll_hints


def test_retained_or_wrong_device_plan_is_discarded_before_queueing(factory, clock):
    b = setup(factory, clock)
    for topic, retain in ((f"P/{SERIAL}/poll_plan", True), ("P/OTHER/poll_plan", False)):
        b.on_mqtt_message(None, None, SimpleNamespace(topic=topic, payload=b"{}", retain=retain))
    assert not b.poll_hints and b.session.request.call_count == 1
