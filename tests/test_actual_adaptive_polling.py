"""Actual worker scheduling with synthetic time, MQTT and cloud only."""

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


def hint(bridge, clock, delay=2400, **changes):
    plan = {
        "version": 1,
        "status_at": bridge.last_success[SERIAL],
        "issued_at": clock(),
        "delay_seconds": delay,
        "reason": "stable",
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
    b = factory(adaptive_polling_enabled=True, adaptive_polling_qualified=True, **options)
    ready(b)
    b.session.request.side_effect = [response(body=STATUS)]
    b.tick()
    return b


def test_new_default_is_fixed_and_each_side_must_be_commissioned(factory, clock):
    for options in ({}, {"adaptive_polling_enabled": True}, {"adaptive_polling_qualified": True}):
        b = factory(**options)
        assert not b.poll_schedule.active
    now = at(MON, 12)
    plan = adaptive.make_plan(now, now, heating=False, has_ct=True, temperature_valid=True)
    assert plan["delay_seconds"] == 2400
    assert (
        adaptive.make_plan(now, now, heating=False, has_ct=False, temperature_valid=True)[
            "delay_seconds"
        ]
        == 1800
    )
    imminent = adaptive.make_plan(
        now, now, heating=True, has_ct=True, temperature_valid=True, completion_at=now + 25 * MIN
    )
    assert imminent["delay_seconds"] == 900 and imminent["reason"] == "near_completion"


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

    s = AdaptiveSchedule(True, lambda: now.wall, lambda: now.mono, path, writer)
    s.observed(SERIAL, now.wall, 1800)
    assert s.accept(
        SERIAL,
        json.dumps(
            {
                "version": 1,
                "status_at": 10000,
                "issued_at": 10000,
                "delay_seconds": 2400,
                "reason": "stable",
            }
        ),
    )
    s.save()
    restored = AdaptiveSchedule(True, lambda: now.wall, lambda: now.mono, path, writer)
    assert restored.counts["accepted"] == 1 and restored.deadline(SERIAL) is None
    now.wall -= 3600
    now.mono += 60
    assert s.deadline(SERIAL) == 2400
    path.write_text("[]", encoding="utf-8")
    assert not AdaptiveSchedule(True, lambda: now.wall, lambda: now.mono, path, writer).active


def test_controller_decision_read_is_bounded_and_freshness_not_relaxed():
    now = at(MON, 12)
    p = adaptive.make_plan(
        now, now - 32 * MIN, heating=False, has_ct=True, temperature_valid=True, decision_at=now
    )
    assert p["delay_seconds"] <= 2400
    assert (
        adaptive.make_plan(
            now, now + timedelta(seconds=1), heating=False, has_ct=True, temperature_valid=True
        )
        is None
    )


def test_real_controller_plans_reach_the_real_bridge_without_command_or_duplicate_http(
    tmp_path, monkeypatch
):
    from test_integration_0_9_0 import Rig, hobart

    rig = Rig(tmp_path, monkeypatch, hobart(MON, 22, 10))
    rig.bridge.options.update(adaptive_polling_enabled=True, adaptive_polling_qualified=True)
    rig.bridge.poll_schedule.enabled = True
    options = {**rig.entry.options, "adaptive_polling_enabled": True}
    rig.entry.options.update(options)
    rig.runtime.apply_options(options, rig.sources)
    rig.executor.configure(options)
    rig.run(hobart(MON + 1, 0, 15))
    assert rig.bridge.poll_schedule.counts["accepted"] > 60
    assert rig.bridge.poll_schedule.counts["ordinary_reads"] < 6
    assert rig.commands() == [] and rig.posts == []
    assert rig.runtime.values["adaptive_polling_status"].startswith("adaptive:")


def test_retained_or_wrong_device_plan_is_discarded_before_queueing(factory, clock):
    b = setup(factory, clock)
    for topic, retain in ((f"P/{SERIAL}/poll_plan", True), ("P/OTHER/poll_plan", False)):
        b.on_mqtt_message(None, None, SimpleNamespace(topic=topic, payload=b"{}", retain=retain))
    assert not b.poll_hints and b.session.request.call_count == 1
