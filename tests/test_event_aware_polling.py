"""Decision-specific freshness and wire limits, synthetic time and I/O only.

0.18.0: the controller no longer creates version-2 ("event-aware") plans; it
sends only Smart v3 plans. The bridge-side v2 tests below build the old wire
format locally (``event``) until the app drops v2 acceptance.
"""

from datetime import timedelta
from datetime import datetime
import importlib
import json

import pytest

from test_shadow_model import m, c
from test_simple_policy import at, MON, sp, snap, TARIFFS
from test_measured_performance import perf, power, meter
from thermowatt_polling import AdaptiveSchedule


def event(
    now,
    status_at,
    *,
    stable_state=None,
    temperature_valid=False,
    decision_at=None,
    owner_check_minutes=60,
    status_max_minutes=45,
):
    """The retired controller v2 plan, kept here only as a wire-format fixture."""
    import math

    owner_limit = int(owner_check_minutes * 60)
    if stable_state in ("baseline", "off"):
        delay, reason = owner_limit, "stable_" + stable_state
    else:
        cap = min(owner_limit, 2400, max(900, (status_max_minutes - 5) * 60))
        next_slot = (math.floor(status_at.timestamp() / 1800) + 1) * 1800
        delay = min(cap, max(900, next_slot - status_at.timestamp()))
        reason = "required_temperature"
        if not temperature_valid:
            delay, reason = 900, "uncertain"
    if isinstance(decision_at, datetime):
        candidate = (decision_at - status_at).total_seconds()
        if candidate < delay:
            delay = max(900, candidate)
            if delay <= 2400:
                reason = "before_decision"
    return {
        "version": 2,
        "status_at": status_at.timestamp(),
        "issued_at": now.timestamp(),
        "delay_seconds": math.floor(delay),
        "reason": reason,
        "owner_check_seconds": owner_limit,
    }


@pytest.mark.parametrize("quiet,minutes", [("baseline", 60), ("off", 90), (None, 60)])
def test_quiet_owner_bound_does_not_extend_temperature_authority(quiet, minutes):
    now = at(MON, 1)
    plan = event(now, now, stable_state=quiet, owner_check_minutes=minutes, temperature_valid=True)
    assert plan["delay_seconds"] == (minutes * 60 if quiet else 1800)
    wall = now.timestamp()
    scheduler = AdaptiveSchedule(True, lambda: wall, lambda: wall, extended_qualified=True)
    scheduler.observed("S", wall, 1800)
    assert scheduler.accept("S", json.dumps(plan))
    assert scheduler.summary("S")["owner_check_seconds"] == minutes * 60


def test_pre_boundary_observation_is_at_actual_decision_not_an_expired_prior():
    now = at(MON, 6)
    decision = now + timedelta(minutes=58)
    plan = event(now, now, stable_state="baseline", decision_at=decision)
    assert plan["delay_seconds"] == 58 * 60
    plan = event(now, now, decision_at=now + timedelta(minutes=25), temperature_valid=True)
    assert plan["delay_seconds"] == 25 * 60


@pytest.mark.parametrize(
    "changes",
    [
        {"version": 1, "delay_seconds": 5400},
        {"owner_check_seconds": True},
        {"owner_check_seconds": 5401},
        {"owner_check_seconds": 1800, "delay_seconds": 3600},
        {"reason": "required_temperature", "delay_seconds": 3600},
    ],
)
def test_extended_plan_cannot_escape_its_purpose_or_owner_bound(changes):
    now = at(MON, 1)
    plan = event(now, now, stable_state="baseline") | changes
    if plan["version"] == 1:
        plan.pop("owner_check_seconds")
    scheduler = AdaptiveSchedule(True, now.timestamp, now.timestamp, extended_qualified=True)
    scheduler.observed("S", now.timestamp(), 1800)
    assert not scheduler.accept("S", json.dumps(plan))


def test_lost_long_lease_returns_to_original_fixed_deadline_without_cached_restart_lease():
    now = at(MON, 1)
    clock = [now.timestamp()]
    scheduler = AdaptiveSchedule(True, lambda: clock[0], lambda: clock[0], extended_qualified=True)
    scheduler.observed("S", clock[0], 1800)
    assert scheduler.accept("S", json.dumps(event(now, now, stable_state="baseline")))
    assert scheduler.deadline("S") == clock[0] + 3600
    clock[0] += 181
    assert scheduler.deadline("S") == now.timestamp() + 1800
    assert scheduler.summary("S")["plan_version"] is None


def test_old_adaptive_qualification_does_not_silently_authorise_long_quiet_checks():
    now = at(MON, 1)
    scheduler = AdaptiveSchedule(True, now.timestamp, now.timestamp)
    scheduler.observed("S", now.timestamp(), 1800)
    assert not scheduler.extended_qualified
    assert not scheduler.accept("S", json.dumps(event(now, now, stable_state="baseline")))
    assert scheduler.deadline("S") == now.timestamp() + 1800


def test_actual_restore_and_undo_preserve_all_new_critical_choices():
    settings = importlib.import_module(f"{m.__package__}.settings")
    protected = {
        "time_zone": "Australia/Perth",
        "daytime_start": "08:30",
        "storage_ready_time": "14:00",
        "baseline_start": "20:00",
        "learned_planning_enabled": True,
        "learning_hardware_qualified": True,
    }
    current = {**c.DEFAULT_OPTIONS, **protected, "forecast_uncertainty": 0.4}
    restored = settings.recommended_options(current)
    for key, value in protected.items():
        assert restored[key] == value and key not in settings.RESTORED
    assert restored["forecast_uncertainty"] == c.DEFAULT_OPTIONS["forecast_uncertainty"]
    undone = settings.undo_restore(restored)
    assert undone["forecast_uncertainty"] == 0.4
    assert all(undone[key] == value for key, value in protected.items())


def test_ct_free_verified_export_can_choose_required_heat_but_never_optional_boost():
    now = at(MON, 11)
    policy = sp.SimplePolicy(sp.PolicySettings(), TARIFFS)
    observation = snap(now, sp.OFF, reading=35, heater_meter_valid=False, required_export_kw=4)
    decision = policy.decide(observation)
    assert decision.state == "normal_storage" and decision.command == "Manual:62"
    assert decision.plan["boost_eligible"] is False


def test_nominal_duration_requires_fresh_probe_and_never_claims_element_on_or_wall_time():
    now = at(MON, 11)
    history = perf.MeasuredHistory()
    for circuit in (power(now, 0), meter.CircuitPower()):
        result = history.completion(now, 40, now, 62, circuit)
        assert result["nominal_continuous_minutes"] > 100
        assert result["earliest"] is None and result["latest"] is None
    result = history.completion(now, 40, now - timedelta(minutes=46), 62, power(now, 0))
    assert result["nominal_continuous_minutes"] is None


def test_passive_lease_suppresses_only_passive_alert_not_command_freshness_gate():
    from test_controller_0_9_0 import ready, obs, cfg, want

    now = at(MON, 1)
    controller = ready(now, "Manual", 45)
    old = obs(
        now, "Manual", 45, poll_age=70 * 60, passive_status_deadline=now + timedelta(minutes=20)
    )
    effects = controller.step(old, want("baseline"), cfg())
    assert not any(e.key == "status_stale" for e in effects)
    assert "heater_status_too_old" in controller.gates(old, "storage", cfg(), "Manual:70@45")
    assert not any(e.kind == "publish" for e in effects)


def setup(factory, clock, **options):
    """A bridge in its pre-Smart adaptive mode (v1/v2 plans), as before 0.18.0."""
    from test_cloud_and_commands import ready
    from conftest import STATUS, response

    b = factory(adaptive_polling_enabled=True, adaptive_polling_qualified=True, **options)
    ready(b)
    b.session.request.side_effect = [response(body=STATUS)]
    b.tick()
    return b


SERIAL = "TEST123"


def test_quiet_ticks_do_not_refresh_auth_until_a_real_read_is_due(factory, clock):
    from conftest import response, STATUS, TOKENS

    bridge = setup(factory, clock, event_aware_polling_qualified=True)
    bridge.proactive_refresh = True
    bridge.token_obtained_at = clock()
    start = clock()
    for _ in range(60):
        now = datetime.fromtimestamp(clock(), m.UTC)
        plan = event(now, datetime.fromtimestamp(start, m.UTC), stable_state="baseline")
        assert bridge.poll_schedule.accept(SERIAL, json.dumps(plan))
        bridge.tick()
        assert bridge.session.request.call_count == 1  # initial status only
        clock.advance(60)
    bridge.session.request.side_effect = [response(body=TOKENS), response(body=STATUS)]
    bridge.tick()
    assert [c.args[0] for c in bridge.session.request.call_args_list] == ["GET", "POST", "GET"]
    assert bridge.usage.counts["token_refresh"] == 1


def test_failed_refresh_after_quiet_period_locks_once_without_status_or_command(
    factory, clock, module
):
    from conftest import response

    bridge = setup(factory, clock, event_aware_polling_qualified=True)
    bridge.proactive_refresh = True
    bridge.token_obtained_at = clock()
    clock.advance(3600)
    bridge.session.request.side_effect = [response(401)]
    bridge.tick()
    count = bridge.session.request.call_count
    assert bridge.guard.state["mode"] == "blocked"
    for _ in range(4):
        clock.advance(3600)
        bridge.tick()
    assert bridge.session.request.call_count == count == 2
