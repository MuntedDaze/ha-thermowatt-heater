"""0.7.0 Phase 2: guest mode and holiday mode (controller-managed). Offline only."""

from datetime import timedelta

import test_controller as tc
from test_controller import c, cfg, ctl, local, m, notices, obs, parked_controller, publishes

goals_mod = tc.goals_mod
SETTINGS, TARIFFS = c.parse_options({})
GUEST = ctl.Desire("permit", "guest_mode", comfort=True, standby=True)


# --- guest mode ---------------------------------------------------------------------


def test_guest_mode_needs_automatic_control_and_no_fault_or_holiday():
    now = local(hour=12)
    disabled = ctl.Controller()
    assert not disabled.start_guest(now) and disabled.refusal == "automatic_control_is_off"
    faulty = parked_controller(now)
    faulty.state = ctl.FAULT_LOCKED
    assert not faulty.start_guest(now)
    assert faulty.refusal == "acknowledge_the_controller_fault_first"
    away = parked_controller(now)
    assert away.set_holiday(now, now - timedelta(hours=1), now + timedelta(days=2))
    assert not away.start_guest(now) and away.refusal == "cancel_holiday_mode_first"


def test_guest_mode_runs_twelve_hours_and_is_persisted():
    now = local(hour=12)
    controller = parked_controller(now)
    assert controller.start_guest(now)
    assert controller.operating_mode(now) == "guest"
    restored = ctl.Controller.from_dict(controller.to_dict())  # HA restart
    restored.restored(now + timedelta(hours=1))
    assert restored.guest_active(now + timedelta(hours=11, minutes=59))
    assert not restored.guest_active(now + timedelta(hours=12))
    assert restored.summary(now)["guest_until"] == (now + timedelta(hours=12)).isoformat()


def test_guest_permit_ignores_economics_and_a_full_tank_but_keeps_gates():
    now = local(hour=17, minute=30)  # peak
    controller = parked_controller(now)
    controller.start_guest(now)
    effects = controller.step(obs(now, temperature_c=66.0), GUEST, cfg())
    assert [e.payload for e in publishes(effects)] == ["Manual:70"]
    # Gates still apply: bridge commands disabled means nothing is sent.
    blocked = parked_controller(now)
    blocked.start_guest(now)
    assert not publishes(blocked.step(obs(now, bridge_commands_enabled=False), GUEST, cfg()))
    assert "bridge_commands_disabled_or_unknown" in blocked.gate_failures


def test_guest_mode_reports_when_it_cannot_be_applied():
    now = local(hour=12)
    controller = parked_controller(now)
    controller.start_guest(now)
    for minute in range(0, 12):
        at = now + timedelta(minutes=minute)
        effects = controller.step(obs(at, poll_at=at, bridge_commands_enabled=False), GUEST, cfg())
    assert "guest_mode_not_applied" in controller.active_alerts
    assert (
        "guest_mode_not_applied" in notices(effects)
        or "guest_mode_not_applied" in controller.alerts
    )


def test_guest_expiry_and_cancel_reinspect_before_normal_control():
    now = local(hour=12)
    controller = parked_controller(now)
    controller.start_guest(now)
    controller.step(obs(now), GUEST, cfg())
    confirm = now + timedelta(seconds=30)
    controller.step(obs(confirm, poll_at=confirm, mode="Manual"), GUEST, cfg())
    assert controller.state == ctl.HEATING_PERMITTED
    end = now + timedelta(hours=12, minutes=1)
    effects = controller.step(
        obs(end, poll_at=end - timedelta(minutes=5), mode="Manual"), tc.PARK, cfg()
    )
    assert controller.guest_until is None and not publishes(effects)
    assert controller.state == ctl.OBSERVING  # re-inspects from a NEW status before acting
    early = parked_controller(now)
    early.start_guest(now)
    assert early.cancel_guest(now + timedelta(hours=1))
    assert early.state == ctl.OBSERVING and early.operating_mode(now) == "automatic"
    assert not early.cancel_guest(now) and early.refusal == "guest_mode_is_not_active"


def test_guest_mode_is_an_owner_instruction_that_releases_hold():
    now = local(hour=12)
    controller = parked_controller(now)
    controller.set_hold(now)
    assert controller.start_guest(now)
    assert controller.hold is False and controller.state == ctl.OBSERVING


def test_owner_app_change_during_guest_mode_still_pauses_control():
    now = local(hour=12)
    controller = parked_controller(now)
    controller.start_guest(now)
    controller.step(obs(now), GUEST, cfg())
    confirm = now + timedelta(seconds=30)
    controller.step(obs(confirm, poll_at=confirm, mode="Manual"), GUEST, cfg())
    later = now + timedelta(minutes=40)
    controller.step(obs(later, poll_at=later, mode="Schedule"), GUEST, cfg())
    assert controller.state == ctl.OWNER_OVERRIDE  # the app wins, even in guest mode


# --- holiday mode ---------------------------------------------------------------------


def test_holiday_dates_are_validated_and_never_adjusted():
    now = local(hour=12)
    controller = parked_controller(now)
    start, back = now + timedelta(hours=2), now + timedelta(days=5)
    assert not controller.set_holiday(now, back, start)
    assert controller.refusal == "return_must_be_after_departure"
    assert not controller.set_holiday(now, start, start + timedelta(days=61))
    assert not controller.set_holiday(now, now - timedelta(days=3), now - timedelta(hours=1))
    assert controller.holiday_start is None  # refusals change nothing
    assert controller.set_holiday(now, start, back)
    assert controller.operating_mode(now) == "automatic"  # not yet departed
    assert controller.operating_mode(start) == "holiday"
    assert controller.cancel_holiday(now) and controller.holiday_window(now) is None


def test_holiday_ends_at_the_return_time_and_survives_restart():
    now = local(hour=12)
    controller = parked_controller(now)
    controller.set_holiday(now, now, now + timedelta(days=2))
    restored = ctl.Controller.from_dict(controller.to_dict())
    assert restored.holiday_active(now + timedelta(days=1))
    back = now + timedelta(days=2, minutes=1)
    restored.step(obs(back, poll_at=back), tc.HOLD, cfg())
    assert restored.holiday_start is None and restored.operating_mode(back) == "automatic"


def test_holiday_goals_drop_comfort_while_away_and_add_one_return_goal():
    now = local(hour=12)
    goals = goals_mod.upcoming_goals(now, SETTINGS, TARIFFS, days=4)
    window = (local(hour=13), local(day=12, hour=15))
    assert all(g.kind != "return" for g in goals_mod.holiday_goals(goals, window, SETTINGS, now))
    planned = goals_mod.holiday_goals(goals, window, SETTINGS, local(day=11, hour=16))
    kinds = [(g.kind, g.deadline) for g in planned]
    assert ("return", local(day=12, hour=15)) in kinds
    assert all(not window[0] <= d < window[1] for kind, d in kinds if kind != "return")
    ret = next(g for g in planned if g.kind == "return")
    assert ret.target_c == SETTINGS.target_c and ret.basis == "holiday_return"


def test_closed_loop_holiday_stays_parked_then_is_ready_for_the_return():
    start = local(hour=5)
    holiday = (start, local(day=12, hour=17))  # away until Thursday 17:00
    sim, controller, trace = tc.closed_loop(start, 61 * 60, 55, economic=True, holiday=holiday)
    rows = {at.astimezone(m.HOBART).strftime("%a %H:%M"): row for at, *row in trace}
    # No morning comfort heating while away (Wed 06:00 would normally heat).
    first = [at for at, payload in sim.posts if payload == "Manual:70"]
    assert not first or first[0] > local(day=12, hour=5)
    assert rows["Thu 17:00"][2] >= 60  # prepared for the return
    assert controller.fault is None
    assert len(sim.posts) <= 4
