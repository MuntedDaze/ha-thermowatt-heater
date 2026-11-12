"""0.7.0 Phase 1: heating PERMISSION vs physical heating, peak-period control
and the 06:00 preferred / 07:00 hard morning deadline. Offline only."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

import test_controller as tc
from test_controller import (
    c,
    cfg,
    ctl,
    local,
    m,
    obs,
    parked_controller,
    plan_mod,
    permitted_controller,
)

permission = tc.permission_mod
strategy = tc.importlib.import_module(f"{m.__package__}.strategy")
goals_mod = tc.goals_mod
SETTINGS, TARIFFS = c.parse_options({})
OFF, PEAK, FEED = 0.1702, 0.361878, 0.09276


def fake_advice(now, surplus, alt_rate=OFF, hours_to_goal=8):
    """Advice stub: future slots priced at `alt_rate` (no forecast solar)."""
    slots = [
        strategy.Slot(
            now + timedelta(minutes=30 + 15 * i),
            now + timedelta(minutes=45 + 15 * i),
            0.25,
            alt_rate,
            0.0,
            0.0,
            0.5,
            0.5,
            False,
        )
        for i in range(24)
    ]
    goals = [goals_mod.Goal("morning", now + timedelta(hours=hours_to_goal), 42, "x", None)]
    return SimpleNamespace(surplus_now_kw=surplus, slots=slots, goals=goals)


def run_policy(policy, start, surpluses, permitted, alt_rate=OFF, peak_soon=False):
    """Feed one surplus per minute; return the decisions."""
    decisions = []
    for minute, surplus in enumerate(surpluses):
        now = start + timedelta(minutes=minute)
        econ = policy.assess(now, fake_advice(now, surplus, alt_rate), SETTINGS, TARIFFS)
        decisions.append(policy.decide(now, econ, permitted, peak_soon))
    return decisions


# --- economics ---------------------------------------------------------------------


def test_break_even_solar_share_at_peak_follows_from_the_tariffs():
    """Peak top-up is worth it only when solar covers enough of the 3 kW:
    share * feed-in + (1 - share) * peak <= off-peak later."""
    share = (PEAK - OFF) / (PEAK - FEED)
    assert share == pytest.approx(0.713, abs=0.001)
    _, at_break_even = permission.blended_cost(share * 3, PEAK, FEED)
    assert at_break_even == pytest.approx(OFF, abs=1e-6)
    _, all_solar = permission.blended_cost(5.0, PEAK, FEED)
    assert all_solar == pytest.approx(FEED)


def test_partial_grid_heating_is_permitted_when_financially_sensible():
    """Off-peak with 1.5 kW of solar beats tonight's off-peak: half solar."""
    policy = permission.StandbyPermission()
    decisions = run_policy(policy, local(hour=12), [1.8] * 12, permitted=False)
    assert decisions[-1][0] == "permit"
    assert policy.last.solar_share == pytest.approx(0.6, abs=0.01)
    assert policy.last.cost_kwh < OFF


def test_permission_needs_ten_sustained_minutes_and_survives_passing_clouds():
    policy = permission.StandbyPermission()
    start = local(hour=17, minute=30)  # peak, Tue
    # Strong sun, then a 4-minute cloud: permission is never withdrawn.
    decisions = run_policy(policy, start, [3.0] * 20 + [0.2] * 4 + [3.0] * 5, permitted=True)
    assert all(action == "permit" for action, *_ in decisions)
    # A sustained loss of solar during the peak withdraws after 5 minutes.
    later = run_policy(policy, start + timedelta(minutes=29), [0.2] * 12, permitted=True)
    actions = [action for action, *_ in later]
    assert "park" in actions and actions.index("park") >= 5
    reason, urgent = later[actions.index("park")][1:]
    assert reason == "peak_import_not_economical" and urgent is True


def test_appliance_spike_does_not_withdraw_permission():
    policy = permission.StandbyPermission()
    start = local(hour=17, minute=30)
    surpluses = [3.2] * 15 + [0.7] * 4 + [3.2] * 10  # 2.5 kW kettle/oven for 4 minutes
    assert all(a == "permit" for a, *_ in run_policy(policy, start, surpluses, permitted=True))


def test_off_peak_withdrawal_waits_ten_minutes_and_grant_requires_a_real_benefit():
    policy = permission.StandbyPermission()
    start = local(hour=12)
    # Off-peak now, solar later is cheaper (alternative 0.10): withdraw after 10 min.
    decisions = run_policy(policy, start, [0.0] * 15, permitted=True, alt_rate=0.10)
    actions = [a for a, *_ in decisions]
    assert actions[:10] == ["permit"] * 10 and "park" in actions[10:]
    # Off-peak now and off-peak later (same price): no switching either way.
    same = permission.StandbyPermission()
    assert run_policy(same, start, [0.0] * 15, permitted=False)[-1][0] == "park"
    same = permission.StandbyPermission()
    assert run_policy(same, start, [0.0] * 15, permitted=True)[-1][0] == "permit"


def test_unknown_meter_never_assumes_solar_and_parks_before_a_peak():
    policy = permission.StandbyPermission()
    now = local(hour=16, minute=40)
    econ = policy.assess(now, fake_advice(now, None), SETTINGS, TARIFFS, decision_at=local(hour=17))
    assert econ.solar_share == 0 and econ.cost_kwh == pytest.approx(PEAK)
    assert policy.decide(now, econ, True, True) == (
        "park",
        "peak_starting_permission_not_economical",
        True,
    )
    assert policy.decide(now, None, True, True)[0] == "park"
    assert policy.decide(now, None, False, False)[0] == "hold"


# --- desire layer -------------------------------------------------------------------


def test_planner_unavailable_morning_failsafe_permits_before_the_hard_deadline():
    window = plan_mod.morning_failsafe_window(local(hour=4), SETTINGS, TARIFFS)
    assert window[1] == local(hour=7) and window[0] == local(hour=3)
    assert window[2] == 42 and window[3] == 0.5  # hard minimum, cooling allowance
    policy = permission.StandbyPermission()
    for hour, reading, expected in (
        (4, 40.0, "permit"),
        (4, None, "permit"),
        (6, 42.5, "permit"),  # 42.0 expected at 07:00 < 42 + 1 allowance
        (6, 44.0, "hold"),  # 43.5 expected: the minimum is safe
        (4, 60.0, "hold"),
        (2, 30.0, "hold"),  # outside the 4-hour window: no blind heating at night
    ):
        now = local(hour=hour)
        desire = plan_mod.desire_from_advice(
            now,
            None,
            False,
            30,
            None,
            standby=policy,
            economics=None,
            reading=reading,
            morning_window=plan_mod.morning_failsafe_window(now, SETTINGS, TARIFFS),
        )
        assert desire.action == expected, (hour, reading)
        if expected == "permit":
            assert desire.comfort and desire.reason == "morning_failsafe_planner_unavailable"


# --- controller gates -------------------------------------------------------------------


def test_standby_permission_is_not_blocked_by_the_thermostat_gate():
    now = local(hour=12)
    controller = parked_controller(now)
    hot = obs(now, temperature_c=66.0)
    plain = controller.gates(hot, "permit", cfg(), True)
    assert "thermostat_would_not_call_for_heat" in plain
    assert controller.gates(hot, "permit", cfg(), True, standby=True) == []


def test_economic_park_during_a_peak_bypasses_minimum_heating_only():
    now = local(hour=17, minute=10)
    controller = permitted_controller(now, since_minutes=10)
    manual = obs(now, mode="Manual", element="on")
    assert "minimum_dwell_not_elapsed" in controller.gates(manual, "park", cfg(), True)
    assert controller.gates(manual, "park", cfg(), True, urgent=True) == []
    # Rest after a park still limits a permit (no rapid cycling).
    parked = parked_controller(now)
    parked.last_transition_at = (now - timedelta(minutes=5)).isoformat()
    assert "minimum_dwell_not_elapsed" in parked.gates(
        obs(now), "permit", cfg(), True, standby=True
    )


def test_standby_permits_use_the_economic_budget_leaving_the_comfort_reserve():
    now = local(hour=12)
    controller = parked_controller(now)
    controller.commands = [(now - timedelta(hours=h)).isoformat() for h in (1, 2, 3, 4)]
    hot = obs(now, temperature_c=66.0)
    failures = controller.gates(hot, "permit", cfg(), True, standby=True)
    assert failures == ["economic_command_budget_reached"]
    assert controller.gates(obs(now), "permit", cfg(), True, comfort=True) == []


def test_owner_change_while_standby_permitted_is_owner_override():
    now = local(hour=13)
    controller = permitted_controller(now)
    desire = ctl.Desire("permit", "economic_permission", standby=True)
    later = now + timedelta(minutes=31)
    controller.step(obs(later, poll_at=later, mode="Off"), desire, cfg())
    assert controller.state == ctl.OWNER_OVERRIDE


def test_restart_needs_sustained_conditions_again_before_granting():
    policy = permission.StandbyPermission()
    run_policy(policy, local(hour=12), [3.0] * 20, permitted=False)
    fresh = permission.StandbyPermission()  # HA restarted: timers are not persisted
    decisions = run_policy(fresh, local(hour=12, minute=20), [3.0] * 5, permitted=False)
    assert all(a == "park" for a, *_ in decisions)


# --- closed loop: bridge model -> advisor -> economics -> controller ------------------------


def posts(sim):
    return [(at.astimezone(m.HOBART).strftime("%H:%M"), payload) for at, payload in sim.posts]


def by_time(trace):
    return {at.astimezone(m.HOBART).strftime("%H:%M"): row for at, *row in trace}


def test_sunny_day_keeps_manual_after_the_thermostat_is_satisfied_and_parks_before_peak():
    sim, controller, trace = tc.closed_loop(local(hour=5), 13 * 60, 45, economic=True)
    assert posts(sim) == [("09:50", "Manual:70"), ("16:49", "off")]
    rows = by_time(trace)
    # The thermostat finished early afternoon; Manual stayed permitted.
    assert rows["15:00"][0] == "Manual" and rows["15:00"][1] is False
    assert rows["17:00"][2] >= 65 and controller.fault is None
    assert tc.peak_grid_minutes(trace, TARIFFS, SETTINGS) == 0


def evening_sun(at):
    """Long summer evening: still ~4 kW at the 17:00 peak start."""
    hour = at.astimezone(m.HOBART).hour + at.astimezone(m.HOBART).minute / 60
    return max(0.0, 5.0 * (1 - ((hour - 14.0) / 6.5) ** 2))


def test_strong_evening_solar_keeps_permission_into_the_peak_then_parks_as_it_fades():
    sim, controller, trace = tc.closed_loop(
        local(hour=5), 14 * 60, 45, pv=evening_sun, draws={11 * 60 + 40: 15.0}, economic=True
    )
    rows = by_time(trace)
    assert rows["17:10"][4] == "heating_permitted"  # permission held across 17:00
    assert rows["17:10"][5] in {
        "solar_justifies_permission_into_peak",
        "economic_permission",
    }
    off_after_peak = [at for at, payload in posts(sim) if payload == "off" and at >= "17:00"]
    assert off_after_peak and off_after_peak[0] <= "19:00"
    assert len(sim.posts) <= 4 and controller.fault is None


def test_shower_just_before_peak_reheats_on_solar_then_parks_without_waiting_for_dwell():
    sim, controller, trace = tc.closed_loop(
        local(hour=5), 12 * 60 + 20, 45, draws={11 * 60 + 30: 15.0}, economic=True
    )
    rows = by_time(trace)
    assert rows["16:35"][0] == "Manual" and rows["16:35"][1] is True  # native reheat at once
    assert ("16:49", "off") in posts(sim)  # 18 min after the element started: dwell bypassed
    # The element consuming exported solar did not look like lost solar (no
    # oscillation): permission was continuous from the shower to the park.
    assert all(rows[f"16:{mm}"][3] == "permit" for mm in range(31, 49))
    # No peak-grid chase of the afternoon storage target afterwards.
    assert all(payload != "Manual:70" for at, payload in posts(sim) if at >= "16:49")


def test_cloudy_day_heats_off_peak_and_never_buys_peak_heat_for_storage():
    sim, controller, trace = tc.closed_loop(
        local(hour=5), 15 * 60, 45, pv=lambda at: 0.2, draws={11 * 60 + 40: 12.0}, economic=True
    )
    assert tc.peak_grid_minutes(trace, TARIFFS, SETTINGS, pv=lambda at: 0.2) == 0
    assert by_time(trace)["16:30"][2] >= 55
    assert not [p for at, p in posts(sim) if p == "Manual:70" and "16:25" < at < "22:00"]


def test_cold_morning_heats_for_06_00_and_never_abandons_07_00():
    sim, controller, trace = tc.closed_loop(local(hour=4, minute=30), 160, 28, economic=True)
    rows = by_time(trace)
    assert posts(sim)[0][1] == "Manual:70" and posts(sim)[0][0] <= "04:35"
    assert rows["06:00"][2] < 42  # 06:00 missed (not enough time from 28 °C)
    assert rows["06:20"][0] == "Manual" and rows["06:20"][3] == "permit"  # continues
    assert rows["07:00"][2] >= 42 and controller.fault is None


def test_winter_morning_minimum_is_protected_into_the_07_00_morning_peak():
    start = local(month=6, day=9, hour=5)  # Tue, AEST: the morning peak starts 07:00
    sim, controller, trace = tc.closed_loop(start, 125, 30, pv=lambda at: 0.0, economic=True)
    rows = by_time(trace)
    # Inside the peak-guard window the minimum is still at risk: keep heating.
    assert rows["06:35"][0] == "Manual" and rows["06:35"][5] == "morning_minimum_at_risk"
    # Parked before the peak only once 42 °C + allowance is expected at 07:00.
    park = [at for at, payload in posts(sim) if payload == "off"]
    assert park and rows[park[0]][2] >= 43
    assert rows["07:00"][2] >= 42 and controller.fault is None


def test_morning_examples_from_the_owner_requirements():
    # 43 °C at 06:00: the minimum is safe (expected 42.5 at 07:00): no heating.
    sim, _, _ = tc.closed_loop(local(hour=6), 60, 43, economic=True)
    assert sim.posts == []
    # 39 °C at 06:00: the hard 07:00 minimum is at risk: heating at once.
    sim, controller, trace = tc.closed_loop(local(hour=6), 61, 39, economic=True)
    assert posts(sim)[0] == ("06:00", "Manual:70")
    assert by_time(trace)["07:00"][2] >= 42
    # 45 °C reached before 06:00: preferred reserve met, nothing more at night.
    sim, _, _ = tc.closed_loop(local(hour=4), 120, 46, economic=True)
    assert sim.posts == []
    # Preferred missed (44 °C just after 06:00): not chased (minimum is safe).
    sim, _, _ = tc.closed_loop(local(hour=6, minute=5), 50, 44, economic=True)
    assert sim.posts == []


def test_weekend_morning_uses_the_same_06_00_and_07_00_deadlines():
    saturday = local(day=14, hour=5)
    goals = goals_mod.upcoming_goals(saturday, SETTINGS, TARIFFS)
    assert goals[0].kind == "morning"
    assert goals[0].deadline == local(day=14, hour=6)
    assert goals[0].hard_deadline == local(day=14, hour=7)


def test_daily_command_count_stays_within_the_limit_over_two_days():
    sim, controller, trace = tc.closed_loop(
        local(hour=5), 48 * 60, 45, draws={15 * 60: 30.0, 39 * 60: 20.0}, economic=True
    )
    times = [at for at, _ in sim.posts]
    for at in times:
        window = [t for t in times if at - timedelta(hours=24) < t <= at]
        assert len(window) <= 6
    assert controller.fault is None
