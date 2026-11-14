"""Measured history, bounded persistence and uncertainty; entirely synthetic."""

from datetime import timedelta
import importlib
import json

import pytest

from test_shadow_model import m
from test_simple_policy import MIN, MON, at
from test_integration_0_9_0 import Rig, drive, hobart

perf = importlib.import_module(f"{m.__package__}.performance")
meter = importlib.import_module(f"{m.__package__}.measurement")
START = at(MON, 12)


def power(at, watts=3000):
    return meter.CircuitPower(watts, at, "on" if watts >= 2000 else "off", "verified")


def session(history, start=START, disturbed=False):
    for i in range(62):
        now = start + i * MIN
        poll = start + (i // 30) * 30 * MIN
        temp = 45 + (poll - start).total_seconds() / 3600 * 3 / m.TANK_KWH_PER_C
        if disturbed and i >= 30:
            temp -= 7
        history.update(power(now, 0 if i == 61 else 3000), temp, poll, "Manual", 70)


def test_real_watts_integrate_once_and_do_not_bridge_outages_or_restarts():
    h = perf.MeasuredHistory()
    for i in range(61):
        h.update(power(START + i * MIN, 2700), None, None, "Manual", 70)
        h.update(power(START + i * MIN, 2700), None, None, "Manual", 70)
    assert h.integrated_kwh == pytest.approx(2.7)
    h.update(meter.CircuitPower(), None, None, "Manual", 70)
    h.update(power(START + 70 * MIN), None, None, "Manual", 70)
    assert h.integrated_kwh == pytest.approx(2.7) and h.gaps == 1
    restored = perf.MeasuredHistory.from_dict(json.loads(json.dumps(h.to_dict())))
    restored.update(power(START + 90 * MIN), None, None, "Manual", 70)
    assert restored.integrated_kwh == pytest.approx(2.7)


def test_counter_loss_recovery_reset_jump_unit_remap_and_duplicate():
    h = perf.MeasuredHistory()
    for minutes, value, identity in [
        (0, 10, "a|kWh"),
        (60, 13, "a|kWh"),
        (60, 13, "a|kWh"),
        (120, 0, "a|kWh"),
        (180, 3, "a|kWh"),
        (181, 100, "a|kWh"),
        (182, 101, "b|kWh"),
    ]:
        h.counter_update(START + minutes * MIN, value, identity)
    assert h.counter_delta_kwh == 6
    assert h.counter_epochs == 3
    restored = perf.MeasuredHistory.from_dict(h.to_dict())
    restored.counter_update(START + 242 * MIN, 104, "b|kWh")
    assert restored.counter_delta_kwh == 9


def test_clean_continuous_heating_yields_one_session_and_draws_are_rejected():
    h = perf.MeasuredHistory()
    session(h)
    assert len(h.sessions) == 1
    assert h.sessions[0]["kwh_per_c"] == pytest.approx(m.TANK_KWH_PER_C)
    dirty = perf.MeasuredHistory()
    session(dirty, disturbed=True)
    assert not dirty.sessions
    assert not h.calibration()["ready"]


def test_learning_needs_independent_sessions_across_days_and_never_controls():
    h = perf.MeasuredHistory()
    for i in range(10):
        session(h, START + timedelta(days=i))
    c = h.calibration()
    assert c["ready"] and c["days"] == 10 and c["sessions"] == 10
    assert c["affects_control"] is False
    assert len(h.to_dict()["sessions"]) <= perf.MAX_SESSIONS


def test_completion_is_conditional_range_and_idle_has_no_wall_clock_promise():
    h = perf.MeasuredHistory()
    result = h.completion(START, 45, START, 70, power(START))
    assert 0 < result["continuous_minutes_low"] < result["continuous_minutes_high"]
    assert result["basis"] == "provisional_bottom_sensor"
    for p in (power(START, 0), meter.CircuitPower()):
        assert h.completion(START, 65, START, 70, p)["latest"] is None
    assert h.completion(START, 45, START + MIN, 70, power(START))["latest"] is None


def test_corrupt_history_and_bounded_persistence():
    h = perf.MeasuredHistory.from_dict(
        {"version": 1, "sessions": [{}, None], "integrated_kwh": float("nan")}
    )
    assert h.integrated_kwh == 0 and not h.sessions
    assert h.should_save(START)
    assert not h.should_save(START + MIN)
    assert h.should_save(START + 15 * MIN)


def test_missing_power_invalidates_a_session_instead_of_learning_nominal_energy():
    h = perf.MeasuredHistory()
    for i in range(62):
        now = START + i * MIN
        h.update(
            meter.CircuitPower() if i == 29 else power(now, 0 if i == 61 else 3000),
            45 + i / 60 * 8,
            now if i % 30 == 0 else None,
            "Manual",
            70,
        )
    assert not h.sessions


def test_event_contract_records_source_times_and_deduplicates(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, hobart(MON, 12))
    rig.run(hobart(MON, 12, 2))
    event = rig.runtime.telemetry
    assert event["schema_version"] == 1 and event["power"]["quality"] == "verified"
    assert event["thermann"]["time_basis"] == "bridge_receipt_not_device_acquisition"
    assert event["calibration"]["affects_control"] is False
    drive(rig.executor.async_step(rig.now()))
    assert rig.runtime.telemetry is event
    json.dumps(event, allow_nan=False)
    assert not rig.posts


def test_fixed_next_poll_uses_utc_clock_and_is_unknown_during_backoff(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, hobart(MON, 12))
    runtime = rig.runtime_module
    due = runtime.background_poll_due(START, 1800, "ok", "clock_aligned")
    assert due.timestamp() % 1800 == 0 and 0 < (due - START).total_seconds() <= 1800
    assert runtime.background_poll_due(START, 1800, "backoff", "clock_aligned") is None
    assert runtime.background_poll_due(START, 1800, "ok", None) is None
    assert runtime.background_poll_due(START, float("nan"), "ok", "clock_aligned") is None
