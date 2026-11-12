"""Scenario report integrity, deadline resilience and shadow-dashboard contracts."""

from datetime import timedelta, time
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from test_shadow_phase2b import c, m, local, readings, cycles, cycle_plan, catalog

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("month,day", [(4, 5), (10, 4), (6, 13), (1, 17)])
@pytest.mark.parametrize("target", [65, 70])
def test_configurable_comfort_and_targets_at_dst_weekends(month, day, target):
    now = local(month=month, day=day, hour=3)
    settings, tariffs = c.parse_options(
        {"target_c": target, "morning_preferred_time": "06:30", "evening_time": "16:30"}
    )
    result = m.evaluate(now, now - timedelta(minutes=1), readings(now, 35, 0), settings, tariffs)
    assert result.deadline == local(month=month, day=day, hour=6, minute=30)
    assert result.planning_target_c == 45 and settings.target_c == target  # 0.7.0 preferred
    assert settings.morning_preferred == time(6, 30) and settings.evening == time(16, 30)


def test_failed_sunshine_forecast_never_moves_conservative_grid_reservation():
    now = local(hour=11)
    settings, tariffs = c.parse_options({})
    data = readings(now, 35, 0)
    clear = m.evaluate(
        now,
        now - timedelta(minutes=1),
        data,
        settings,
        tariffs,
        (m.Forecast(now, now + timedelta(hours=5), 4),),
    )
    cloudy = m.evaluate(now, now - timedelta(minutes=1), data, settings, tariffs)
    assert clear.grid_fallback_start == cloudy.grid_fallback_start
    at = cloudy.grid_fallback_start
    result = m.evaluate(at, at - timedelta(minutes=1), readings(at, 35, 0), settings, tariffs)
    policy = cycles.CyclePolicy(stopped=at)
    assert (
        policy.step(at, result, settings, tariffs, sample_at=at)["reason"]
        == "comfort_overrides_economic_hold_and_gap"
    )


@pytest.mark.parametrize(
    "state",
    ["shadow_blocked", "shadow_native_intervention", "shadow_paused", "shadow_awaiting_validation"],
)
def test_cloud_quota_outage_fault_and_owner_gates_suspend_simulated_dwell(state):
    now = local(hour=11)
    settings, tariffs = c.parse_options({})
    plan = cycle_plan(now, now + timedelta(hours=5))
    policy = cycles.CyclePolicy(active=True, started=now, goal=plan.deadline, goal_energy=12)
    plan.state = state
    result = policy.step(now, plan, settings, tariffs, sample_at=now)
    assert not policy.active and result["state"] == "suspended"


def test_new_temperature_shortage_invalidates_completed_counterfactual():
    now = local(hour=11)
    settings, tariffs = c.parse_options({})
    plan = cycle_plan(now, now + timedelta(hours=5), minutes=60)
    policy = cycles.CyclePolicy(
        goal=plan.deadline, goal_energy=3, delivered=3, last_observed_energy=3
    )
    result = policy.step(now, plan, settings, tariffs, sample_at=now)
    assert result["state"] == "simulated_satisfied"
    plan.mixed_model_energy_kwh = 5
    result = policy.step(
        now + timedelta(minutes=1), plan, settings, tariffs, sample_at=now + timedelta(minutes=1)
    )
    assert result["simulated_remaining_kwh"] == 5 and policy.delivered == 0


def test_minimum_gap_and_stop_dwell_are_real_constraints():
    now = local(hour=11)
    settings, tariffs = c.parse_options({"switching_benefit_aud": 0.01})
    policy = cycles.CyclePolicy(stopped=now)
    deadline = now + timedelta(hours=6)
    for minute in range(31):
        at = now + timedelta(minutes=minute)
        result = policy.step(at, cycle_plan(at, deadline), settings, tariffs, sample_at=at)
        assert policy.active == (minute == 30)
    assert result["simulated_cycle_count"] == 1
    # Even a large new disadvantage cannot stop before 30 minutes, then the
    # already sustained 20-minute loss can qualify at the dwell boundary.
    for minute in range(31, 61):
        at = now + timedelta(minutes=minute)
        policy.step(
            at,
            cycle_plan(at, deadline, 0),
            settings,
            tariffs,
            (m.Forecast(at + timedelta(minutes=15), deadline, 3),),
            at,
        )
        assert policy.active == (minute < 60)


def test_synthetic_report_reproduces_counts_costs_and_equal_served_energy():
    spec = importlib.util.spec_from_file_location(
        "cycle_replay_test", ROOT / "tools/replay_shadow_cycles.py"
    )
    replay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay)
    saved = json.loads(
        (ROOT / "shadow_controller/CYCLE_SCENARIO_RESULTS.json").read_text(encoding="utf-8-sig")
    )
    for row in saved["rows"]:
        for fast, key in [(False, "stateful"), (True, "instantaneous_benchmark")]:
            result = replay.replay_case(
                row["cloud_minutes"],
                row["scenario"] == "peak_transition",
                row["scenario"] == "approaching_deadline",
                fast,
            )
            assert result == row[key]
            assert result["delivered_kwh"] == 6 and result["shortfall_kwh"] == 0
    assert {row["cloud_minutes"] for row in saved["rows"]} == {2, 5, 10, 20, 30, 60}
    assert saved["cloud_requests"] == saved["physical_heater_operations"] == 0


def test_dashboard_and_generated_setting_defaults_are_current_and_no_heater_actions():
    spec = importlib.util.spec_from_file_location(
        "dashboard_test", ROOT / "tools/build_shadow_dashboard.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    dashboard = yaml.safe_load(
        (ROOT / "shadow_controller/dashboard.yaml").read_text(encoding="utf-8")
    )
    assert dashboard == builder.build()
    assert [view["title"] for view in dashboard["views"]] == [
        "Hot Water",
        "Settings",
        "Diagnostics",
    ]
    content = json.dumps(dashboard)
    for key, meta in catalog.CATALOG.items():
        assert meta.explanation and key in c.DEFAULT_OPTIONS
        if meta.kind != "form" and meta.group != "Legacy":
            assert builder.entity(key) in content
        elif meta.group == "Legacy":
            # 0.7.0: kept so saved settings are unchanged, never shown.
            assert builder.entity(key) not in content
    assert "recommended & original" in content and "confirmation" in content
