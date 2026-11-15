"""Real-measurement architecture tested with synthetic observations, not commissioned."""

from datetime import timedelta
from dataclasses import replace
import copy
import importlib
import pytest

from test_shadow_model import m
from test_measured_performance import power, perf, START
from test_simple_policy import sp, TARIFFS, snap

learn = importlib.import_module(f"{m.__package__}.learning")
MIN = timedelta(minutes=1)


def captured(history, start, target=62, fraction=1):
    rate = history.nominal_kw / history.physics * fraction
    history.update(power(start - MIN, 0), 35, start - MIN, "Manual", target)
    for i in range(62):
        now = start + i * MIN
        poll = start + (i // 30) * 30 * MIN
        temp = 35 + (poll - start).total_seconds() / 3600 * rate
        history.update(power(now, 0 if i == 61 else 3000), temp, poll, "Manual", target)


def dataset(target=62, hold_fraction=1):
    history = perf.MeasuredHistory()
    history.configure(315, 3, "sensor.synthetic_ct|W")
    for day in range(10):
        for hour in (0, 3):
            captured(
                history,
                START + timedelta(days=day, hours=hour),
                target,
                hold_fraction if day >= 7 else 1,
            )
    now = START + timedelta(days=11)
    return history, now


def metrics(history, now, target=62):
    return learn.evaluate(
        list(history.sessions),
        target,
        history.tank_litres,
        history.nominal_kw,
        history.meter_identity,
        now,
    )


def test_complete_session_details_and_heldout_fit_survive_restart():
    history, now = dataset()
    row = history.sessions[0]
    assert row["complete_start"] is True and row["started_at"] < row["at"]
    assert row["covered_cycle_energy_kwh"] == pytest.approx(3.025)
    result = metrics(history, now)
    assert result["eligible"] and result["heldout_sessions"] >= 5 and result["heldout_days"] >= 2
    assert result["heldout_mae_minutes"] == pytest.approx(0, abs=0.00001)
    assert result["conservative_coverage"] == 1
    restored = perf.MeasuredHistory.from_dict(copy.deepcopy(history.to_dict()))
    assert metrics(restored, now) == result
    assert restored.last is None and restored.cycle is None


def test_bounded_history_can_retain_all_three_qualified_target_cohorts():
    history = perf.MeasuredHistory()
    history.configure(315, 3, "sensor.synthetic_ct|W")
    for day in range(10):
        for hour, target in enumerate((45, 62, 70, 45, 62, 70)):
            captured(history, START + timedelta(days=day, hours=hour * 2), target)
    assert len(history.sessions) == 60 <= perf.MAX_SESSIONS
    restored = perf.MeasuredHistory.from_dict(copy.deepcopy(history.to_dict()))
    for target in (45, 62, 70):
        result = metrics(restored, START + timedelta(days=11), target)
        assert result["sessions"] == 20 and result["eligible"]


def test_changed_heldout_data_cannot_leak_into_fit_or_pass_optimistic_coverage():
    good, now = dataset()
    bad, _ = dataset(hold_fraction=0.8)
    result = metrics(bad, now)
    assert result["fitted_c_per_hour"] == pytest.approx(metrics(good, now)["fitted_c_per_hour"])
    assert not result["eligible"] and result["conservative_coverage"] < 0.9
    assert learn.planning(result, True, True, True)[1].startswith("nominal_")


@pytest.mark.parametrize(
    "enabled,qualified,verified", [(False, True, True), (True, False, True), (True, True, False)]
)
def test_each_explicit_gate_is_required(enabled, qualified, verified):
    history, now = dataset()
    result = metrics(history, now)
    value, basis = learn.planning(result, enabled, qualified, verified)
    assert basis.startswith("nominal_") and value == result["nominal_c_per_hour"]


def test_duplicate_missing_wrong_target_remapped_and_old_data_never_authorise_learning():
    history, now = dataset()
    rows = list(history.sessions)
    for sample, target, identity, when in (
        (rows[:2] * 10, 62, history.meter_identity, now),
        (rows, 70, history.meter_identity, now),
        (rows, 62, "sensor.other|W", now),
        (rows, 62, history.meter_identity, now + timedelta(days=40)),
    ):
        assert not learn.evaluate(sample, target, 315, 3, identity, when)["eligible"]
    rows[0].pop("model_version")
    rows = rows[:1] * 20
    assert not learn.evaluate(rows, 62, 315, 3, history.meter_identity, now)["eligible"]


def test_qualified_learning_can_only_advance_required_start_and_never_speed_live_watts():
    now = START.replace(hour=1)  # morning local; choose a fresh required daytime test below
    from test_simple_policy import at, MON

    now = at(MON, 13)
    policy = sp.SimplePolicy(sp.PolicySettings(boost_enabled=False), TARIFFS)
    original = policy.decide(snap(now, sp.OFF, reading=40, heater_meter_valid=False))
    slower = policy.decide(
        snap(now, sp.OFF, reading=40, heater_meter_valid=False, learned_rates={62: 6})
    )
    assert slower.plan["latest_start"] <= original.plan["latest_start"]
    assert slower.plan["planning_rate_basis"] == "learned_conservative_lower_bound"
    assert (
        policy._target_rate(
            replace(snap(now, sp.OFF), measured_element_kw=2.2, learned_rates={62: 8}), 62
        )
        <= 2.2 / policy.s.kwh_per_c
    )


def test_first_seen_running_cycle_is_diagnostic_without_a_verified_start():
    history, now = dataset()
    row = copy.deepcopy(history.sessions[0])
    row["complete_start"] = False
    assert not learn.evaluate([row] * 20, 62, 315, 3, history.meter_identity, now)["eligible"]
