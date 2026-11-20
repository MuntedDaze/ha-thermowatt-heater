"""Restore/undo, CT-free and freshness guards (synthetic time and I/O only).

0.18.0 / 1.5.0: the pre-Smart version-2 ("event-aware") plans are removed and
their bridge tests with them. Smart plan tests: test_actual_adaptive_polling.py,
test_next_major_polling.py and test_smart_plan_acceptance_1_4_1.py.
"""

from datetime import timedelta
import importlib

from test_shadow_model import m, c
from test_simple_policy import at, MON, sp, snap, TARIFFS
from test_measured_performance import perf, power, meter


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
