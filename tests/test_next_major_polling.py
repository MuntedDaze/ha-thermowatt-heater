"""Long quiet leases and authentication reuse exercise the real bridge worker."""

from datetime import timedelta
import importlib
import json

import pytest

from test_shadow_model import m
from test_simple_policy import at, MON, MIN
from thermowatt_polling import AdaptiveSchedule
from test_cloud_and_commands import ready
from conftest import STATUS, response

adaptive = importlib.import_module(f"{m.__package__}.adaptive")


@pytest.mark.parametrize("mode,hours", [("smart", 8)])
def test_quiet_interval_is_bounded_and_lost_lease_is_fixed30(mode, hours):
    now = at(MON, 22)
    wall = [now.timestamp()]
    schedule = AdaptiveSchedule(True, lambda: wall[0], lambda: wall[0], smart_mode=mode)
    schedule.observed("S", wall[0], 1800)
    plan = adaptive.smart_plan(now, now, stable_state="baseline", overnight=True)
    assert plan["delay_seconds"] == hours * 3600
    assert schedule.accept("S", json.dumps(plan))
    assert schedule.deadline("S") == wall[0] + hours * 3600
    wall[0] += 181
    assert schedule.deadline("S") == now.timestamp() + 1800


def test_pre_peak_read_and_later_exact_prior_are_distinct_useful_events():
    now = at(MON, 22)
    check = now + timedelta(hours=7, minutes=30)
    plan = adaptive.smart_plan(now, now, stable_state="baseline", overnight=True, decision_at=check)
    assert plan["reason"] == "quiet_before_decision"
    assert plan["delay_seconds"] == 7.5 * 3600
    schedule = AdaptiveSchedule(True, now.timestamp, now.timestamp, smart_mode="smart")
    schedule.observed("S", now.timestamp(), 1800)
    assert schedule.accept("S", json.dumps(plan))
    assert (
        adaptive.smart_plan(check, check, stable_state="baseline", decision_at=check + 28 * MIN)[
            "delay_seconds"
        ]
        == 28 * 60
    )


@pytest.mark.parametrize(
    "change",
    [
        {"owner_check_seconds": 43201},
        {"delay_seconds": 28801},
        {"reason": "required_temperature", "delay_seconds": 28800},
        {"owner_check_seconds": True},
        {"polling_mode": "minimum"},
        {"issued_at": 0},
        {"status_at": 0},
    ],
)
def test_v3_rejects_excessive_mislabelled_stale_or_wrong_anchor(change):
    now = at(MON, 22)
    plan = adaptive.smart_plan(now, now, stable_state="baseline", overnight=True) | change
    schedule = AdaptiveSchedule(True, now.timestamp, now.timestamp, smart_mode="smart")
    schedule.observed("S", now.timestamp(), 1800)
    assert not schedule.accept("S", json.dumps(plan))


def test_new_permission_does_not_fabricate_old_qualification():
    now = at(MON, 22)
    plan = adaptive.smart_plan(now, now, stable_state="baseline", overnight=True)
    old = AdaptiveSchedule(True, now.timestamp, now.timestamp, extended_qualified=True)
    old.observed("S", now.timestamp(), 1800)
    assert not old.accept("S", json.dumps(plan))
    new = AdaptiveSchedule(True, now.timestamp, now.timestamp, smart_mode="smart")
    new.observed("S", now.timestamp(), 1800)
    assert not new.extended_qualified
    assert new.accept("S", json.dumps(plan))


def test_explicit_smart_ordinary_get_reuses_token_without_a_lifetime_assumption(factory, clock):
    b = factory(polling_mode="smart")
    ready(b)
    b.discovered = True
    b.token_obtained_at = clock()
    clock.advance(1801)
    b.session.request.side_effect = [response(body=STATUS)]
    b.request("GET", "/status", "TEST123")
    assert b.session.request.call_count == 1
    assert b.request_counts["token_refresh"] == 0
    assert not b.options.get("event_aware_polling_qualified", False)


def test_expired_smart_get_uses_existing_one_refresh_one_retry(factory, clock):
    b = factory(polling_mode="smart")
    ready(b)
    b.discovered = True
    b.token_obtained_at = clock()
    clock.advance(1801)
    b.session.request.side_effect = [
        response(401),
        response(
            body={"result": {"accessToken": "synthetic_new", "refreshToken": "synthetic_refresh"}}
        ),
        response(body=STATUS),
    ]
    b.request("GET", "/status", "TEST123")
    assert b.session.request.call_count == 3
    assert b.request_counts["token_refresh"] == 1
    assert [call.args[0] for call in b.session.request.call_args_list] == ["GET", "POST", "GET"]
