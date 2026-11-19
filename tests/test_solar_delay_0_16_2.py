"""Controller 0.16.2: avoidable morning solar-boost delays (synthetic evidence).

1. The rolling command count is evaluated at the decision time with a
   half-open 24-hour window. Peak boundaries recur at the same clock time, so
   yesterday's boundary command must not reserve today's optional budget.
2. A current valueless GoodWe report ("unavailable") is a gap, not a
   below-threshold vote. Before any optional session it no longer erases
   genuine qualification; the existing gap/freshness limits still apply and an
   active session keeps the latched protective loss unchanged.
"""

from datetime import timedelta
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_integration_0_9_0 import Rig, hobart, drive, c
from test_existing_installation_upgrade import ct_free
from test_audit_regressions_0_9_1 import controller_ready

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

MIN = timedelta(minutes=1)


def test_command_exactly_24_hours_old_no_longer_counts():
    now = hobart(19, 11)
    ctl = controller_ready(now, "Off", 45)
    ctl.commands = [
        (now - timedelta(hours=24)).isoformat(),
        (now - timedelta(hours=24) + timedelta(seconds=1)).isoformat(),
    ]
    assert ctl.commands_in_window(now) == 1
    assert ctl.commands_in_window(now + timedelta(seconds=1)) == 0


def captured(rig, value, when):
    state = SimpleNamespace(
        state=str(value), last_reported=when, attributes={"unit_of_measurement": "W"}
    )
    event = SimpleNamespace(data={"entity_id": c.DEFAULT_SOURCES["grid"], "new_state": state})
    rig.runtime.capture_input_report(event, when)


def ct_free_rig(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, hobart(19, 11, 30), mode="Manual", setpoint=62)
    ct_free(rig)
    return rig


def test_unavailable_report_before_a_session_pauses_but_never_satisfies(tmp_path, monkeypatch):
    rig = ct_free_rig(tmp_path, monkeypatch)
    p, now = rig.executor.policy, rig.now()
    for i in range(10):
        p.add_meter(now - (10 - i) * MIN, -4, heater_kw=0)
    captured(rig, "unavailable", now - timedelta(seconds=30))
    assert len(p.samples) == 10 and not rig.runtime.solar_input_loss_pending
    captured(rig, 4000, now)
    # The minute around the gap is unmeasured: 10 elapsed minutes contain
    # only 9 measured ones, so qualification is NOT yet satisfied.
    assert not p.surplus_qualified(now)
    captured(rig, 4000, now + MIN)
    assert p.surplus_qualified(now + MIN)


def test_gap_time_never_counts_as_confirmed_export():
    from test_simple_policy import S, TARIFFS, sp, at, MON

    p = sp.SimplePolicy(S, TARIFFS)
    t0 = at(MON, 12)
    for minute in range(5):
        p.add_meter(t0 + minute * MIN, -4, heater_kw=0)
    p.note_missing()  # minutes 4 -> 7 are unmeasured
    for minute in range(7, 14):
        p.add_meter(t0 + minute * MIN, -4, heater_kw=0)
        assert p.surplus_qualified(t0 + minute * MIN) is (minute >= 13), minute
    # A failing measured report after the gap still resets as before.
    p.add_meter(t0 + 14 * MIN, -1, heater_kw=0)
    assert not p.surplus_qualified(t0 + 14 * MIN)


def test_an_outage_longer_than_the_meter_age_still_breaks_qualification(tmp_path, monkeypatch):
    rig = ct_free_rig(tmp_path, monkeypatch)
    p, now = rig.executor.policy, rig.now()
    for i in range(10):
        p.add_meter(now - (10 - i) * MIN, -4, heater_kw=0)
    for second in (30, 90, 150, 210):
        captured(rig, "unavailable", now + timedelta(seconds=second))
    later = now + timedelta(seconds=240)
    captured(rig, 4000, later)
    assert not p.surplus_qualified(later)  # a > 3 min gap is never bridged


@pytest.mark.parametrize("value", ["unavailable", "unknown", "garbage"])
def test_session_keeps_the_latched_protective_loss(tmp_path, monkeypatch, value):
    rig = ct_free_rig(tmp_path, monkeypatch)
    rig.executor.controller.solar_session_active = True
    p, now = rig.executor.policy, rig.now()
    for i in range(10):
        p.add_meter(now - (10 - i) * MIN, -4, heater_kw=0)
    captured(rig, value, now)
    assert not p.samples and rig.runtime.solar_input_loss_pending


def test_implausible_or_unverified_reports_still_reset(tmp_path, monkeypatch):
    rig = ct_free_rig(tmp_path, monkeypatch)
    p, now = rig.executor.policy, rig.now()
    for i in range(10):
        p.add_meter(now - (10 - i) * MIN, -4, heater_kw=0)
    captured(rig, 20000, now)  # export beyond 110% of the inverter limit
    assert not p.samples


@pytest.mark.parametrize("ct", [False, True])
def test_no_optional_start_on_a_tick_whose_meter_report_has_no_value(tmp_path, monkeypatch, ct):
    rig = Rig(
        tmp_path,
        monkeypatch,
        hobart(19, 11, 30),
        mode="Manual",
        setpoint=45,
        reading=45,
        pv=lambda local: 6.5,
    )
    if not ct:
        ct_free(rig)
    rig.entry.options.update(normal_storage_c="62")
    rig.runtime.apply_options(rig.entry.options, rig.sources)
    rig.executor.configure(rig.entry.options)
    rig.pv = lambda local: 0.0
    rig.enable()
    rig.run(rig.now() + 35 * MIN)  # a confirmed status after enabling, no export yet
    assert rig.executor.controller.state != "observing"
    rig.pv = lambda local: 6.5
    rig.run(rig.now() + 9 * MIN)  # nine minutes of strong export: not yet qualified
    p = rig.executor.policy
    rig.t += 60
    rig.tank.minute(rig.t)
    rig._meter()
    rig.report("sensor.synthetic_heater_w", 0, {"unit_of_measurement": "W"})
    # Ten minutes have elapsed, but the latest grid report has no value.
    rig.report(c.DEFAULT_SOURCES["grid"], "unavailable", {"unit_of_measurement": "W"})
    before = list(rig.commands())
    rig.runtime.update(rig.now())
    drive(rig.executor.async_step(rig.now()))
    plan = rig.executor.last_decision.plan
    assert rig.commands() == before  # nothing sent on stale meter data
    assert not p.surplus_qualified(rig.now())  # and the gap counted for nothing
    if ct:
        # A CT installation needs a paired fresh grid report for its power
        # budget, so the gap still resets qualification exactly as in 0.16.1.
        assert plan["boost_reason"] == "verified_circuit_and_grid_required"
        assert not p.samples
    else:
        assert plan["boost_reason"] == "grid_measurement_missing"
        assert len(p.samples) >= 9  # earlier genuine votes kept (a pause, not a reset)


def _run(name):
    import morning_solar_delay_replay as replay

    data = replay.results([name])
    return data["runs"][0]


def test_replay_patchy_day_does_not_reserve_the_next_boundary_boost():
    row = _run("patchy_wednesday_then_clear")
    assert row["thursday_posts"][:2] == [["07:58", "off"], ["11:00", 70]]
    assert (
        "optional_budget_reserved_for_essential_heat"
        not in row["qualified_not_at_70_minutes_by_boost_reason"]
    )


def test_replay_isolated_goodwe_gaps_no_longer_force_normal_first():
    row = _run("goodwe_unavailable_every_7_min")
    assert row["first_qualified_export"] == "09:06"  # gap minutes paused, not counted
    assert row["thursday_posts"][1] == ["11:00", 70]


def test_replay_peak_lockout_remains_the_designed_morning_restriction():
    row = _run("clear_peak_never")
    assert row["thursday_posts"] == [["07:58", "off"], ["11:00", 70]]
    assert row["qualified_minutes_blocked_by"] == {"peak_heating_locked_out | peak_lockout": 120}


# --- exact measured-duration qualification (independent review, 19 Nov) ---------------


def _policy():
    from test_simple_policy import S, TARIFFS, sp

    return sp.SimplePolicy(S, TARIFFS)


def _t(minute):
    from test_simple_policy import at, MON

    return at(MON, 12) + timedelta(minutes=minute)


def _feed(p, valid, missing=(), kw=-4.0, upto=None):
    """Replay reports in time order; returns {minute: qualified}."""
    out = {}
    events = sorted([(m, "ok") for m in valid] + [(m, "gap") for m in missing])
    for minute, kind in events:
        if kind == "gap":
            p.note_missing()
        else:
            p.add_meter(_t(minute), kw(minute) if callable(kw) else kw, heater_kw=0)
            out[minute] = p.surplus_qualified(_t(minute))
    return out


def test_reviewer_case_three_two_minute_gaps_needs_ten_measured_minutes():
    p = _policy()
    valid = [4, 6, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
    result = _feed(p, valid, missing=[5, 7, 10])
    assert [
        (round((a - _t(0)).total_seconds() / 60), round((b - _t(0)).total_seconds() / 60))
        for a, b in p.unmeasured
    ] == [(4, 6), (6, 8), (9, 11)]
    # Minute 19: 15 elapsed, 6 unmeasured, 9 measured -> NOT qualified.
    assert result[19] is False
    assert result[20] is True  # 16 elapsed - 6 unmeasured = 10 measured


def test_consecutive_missing_reports_form_one_interval_not_double_counted():
    p = _policy()
    result = _feed(p, [0, 1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12], missing=[4, 4.5])
    assert len(p.unmeasured) == 1  # [3, 5]
    assert result[11] is False and result[12] is True


def test_overlapping_or_adjacent_intervals_are_merged_exactly():
    p = _policy()
    p.unmeasured.extend([(_t(2), _t(5)), (_t(4), _t(6)), (_t(6), _t(7)), (_t(9), _t(10))])
    assert p._unmeasured_within(_t(0), _t(20)) == timedelta(minutes=6)  # [2,7] + [9,10]
    assert p._unmeasured_within(_t(3), _t(9.5)) == timedelta(minutes=4.5)


def test_irregular_report_spacing_without_gaps_qualifies_exactly_at_ten_minutes():
    p = _policy()
    result = _feed(p, [0, 2.5, 3.0, 5.75, 8.0, 9.9, 10.0])
    assert result[9.9] is False and result[10.0] is True


def test_report_spacing_over_the_meter_age_never_qualifies():
    p = _policy()
    result = _feed(p, [0, 2, 5.5, 8, 10, 12, 14])  # 2 -> 5.5 exceeds 3 minutes
    assert result[12] is False  # the window cannot reach back across the hole
    assert result[14] is False  # 5.5 -> 14 is only 8.5 minutes


def test_repeated_short_gaps_accrue_only_measured_time():
    p = _policy()
    valid = [m for m in range(0, 30, 2)]  # a report every 2 min
    missing = [m + 1 for m in range(0, 28, 2)]  # each followed by a valueless one
    result = _feed(p, valid, missing=missing)
    # Every 2-minute interval is unmeasured: measured time never accumulates.
    assert not any(result.values())


def test_stale_latest_report_or_open_gap_fails_closed():
    p = _policy()
    _feed(p, list(range(0, 12)))
    assert p.surplus_qualified(_t(11))
    assert not p.surplus_qualified(_t(11) + timedelta(minutes=3, seconds=1))  # stale
    p.note_missing()  # a gap is open now
    assert not p.surplus_qualified(_t(11) + timedelta(seconds=30))


def test_report_timestamps_cannot_be_duplicated_or_reordered_into_votes():
    p = _policy()
    for _ in range(20):
        p.add_meter(_t(0), -4, heater_kw=0)  # the same report repeated
    p.add_meter(_t(5), -4, heater_kw=0)
    p.add_meter(_t(3), -4, heater_kw=0)  # older than the latest: ignored
    assert len(p.samples) == 2 and not p.surplus_qualified(_t(5))


def test_measured_below_threshold_report_still_resets_after_gaps():
    p = _policy()
    result = _feed(
        p,
        list(range(0, 4)) + list(range(6, 30)),
        missing=[5],
        kw=lambda m: -1.0 if m == 12 else -4.0,
    )
    assert result[13] is False and result[22] is False
    assert result[23] is True  # ten measured minutes from the first passing report (13)


def test_reset_marker_is_still_honoured():
    p = _policy()
    _feed(p, list(range(0, 12)))
    p.surplus_reset_at = _t(5)
    assert not p.surplus_qualified(_t(11))


def test_unmeasured_intervals_never_change_import_withdrawal():
    p = _policy()
    for minute in range(0, 4):
        p.add_meter(_t(minute), 0.5, heater_kw=0)
    p.note_missing()
    for minute in range(5, 12):
        p.add_meter(_t(minute), 0.5, heater_kw=0)
    # Withdrawal keeps its original elapsed-time rule (no extension by gaps).
    assert p.importing_continuously(_t(11))
