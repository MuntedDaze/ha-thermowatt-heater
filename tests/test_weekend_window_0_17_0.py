"""Controller 0.17.0: the owner's weekend comfort window (synthetic evidence)."""

from dataclasses import replace
from pathlib import Path
import sys

import pytest

from test_simple_policy import sp, S, TARIFFS, at, MON, SAT, SUN, snap, fc, BASE

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

S62 = replace(S, normal_c=62, boost_enabled=False)
NORMAL = sp.NORMAL


def policy(settings=S62):
    return sp.SimplePolicy(settings, TARIFFS)


def test_first_fresh_500_w_report_opens_before_9_without_qualification():
    p = policy()
    now = at(SAT, 6, 5)
    p.add_pv(now, 0.5)
    d = p.decide(snap(now, BASE, reading=50, heater_meter_valid=False))
    assert d.plan["weekend_window_opened_by"] == "measured_pv"
    assert d.plan["weekend_day_latched"] and d.plan["weekend_grid_assistance_permitted"]
    assert (d.state, d.reason) == (NORMAL, "weekend_storage_no_forecast")
    assert d.plan["heating_role"] == "weekend_comfort"


def test_open_window_schedules_62_economically_before_the_deadline():
    p = policy()
    now = at(SUN, 7)
    p.add_pv(now, 0.6)
    # Little surplus now, full solar from 10:00: wait, and say until when.
    later = fc(now, 9, lambda i: 0.0 if i < 6 else 4.0)
    d = p.decide(snap(now, BASE, reading=48, forecast=later, heater_meter_valid=False))
    assert (d.state, d.reason, d.command) == (BASE, "storage_waiting_for_cheaper_window", None)
    assert at(SUN, 9, 45) <= d.plan["best_start"] <= at(SUN, 10)
    assert d.plan["latest_start"] < d.plan["soft_target"] == at(SUN, 15, 30)
    # At the best start the same window starts 62.
    p.add_pv(at(SUN, 10), 3.5)
    d = p.decide(snap(at(SUN, 10), BASE, reading=47, forecast=later[6:], weekend_latched=True))
    assert d.command == "Manual:62" and d.reason == "storage_cheapest_now"


def test_latest_start_is_firm_even_if_the_forecast_promises_later_sun():
    p = policy()
    now = at(SAT, 13)
    d = p.decide(
        snap(
            now,
            BASE,
            reading=40,
            forecast=fc(now, 5, lambda i: 0 if i < 4 else 5),
            weekend_latched=True,
        )
    )
    assert d.command == "Manual:62" and d.reason in {
        "storage_latest_start",
        "storage_target_may_be_missed",
    }


def test_selected_62_is_never_paused_inside_the_window():
    p = policy()
    now = at(SAT, 9)
    d = p.decide(
        snap(
            now,
            NORMAL,
            reading=50,
            forecast=fc(now, 8, lambda i: 0 if i < 4 else 5),
            weekend_latched=True,
        )
    )
    assert (d.state, d.command) == (NORMAL, None)


@pytest.mark.parametrize("reading,opens", [(40, True), (55, False)])
def test_deadline_fallback_only_when_the_tank_needs_heat(reading, opens):
    p = policy()
    d = p.decide(snap(at(SAT, 15), BASE, reading=reading, heater_meter_valid=False))
    assert (d.plan.get("weekend_window_opened_by") == "deadline_fallback") is opens
    assert (d.state == NORMAL) is opens


def test_unknown_temperature_plans_conservatively_and_still_meets_the_deadline():
    p = policy()
    now = at(SAT, 12, 30)
    d = p.decide(snap(now, BASE, reading=None, reading_at=None, heater_meter_valid=False))
    assert d.plan["reading_fresh"] is False
    assert d.state == NORMAL and d.plan["weekend_window_opened_by"] == "deadline_fallback"


def test_end_time_returns_to_45_and_monday_is_unchanged():
    p = policy()
    d = p.decide(snap(at(SUN, 18), NORMAL, reading=61, weekend_latched=True))
    assert (d.state, d.reason, d.command) == (BASE, "weekend_day_ended", "Manual:45")
    p.add_pv(at(MON, 6, 30), 2.0)
    monday = p.decide(snap(at(MON, 6, 30), BASE, reading=50))
    assert "weekend_window_opened_by" not in monday.plan and monday.state == BASE


def _weekend(name):
    import weekend_replay

    return weekend_replay.results([name])["runs"][0]["days"]


@pytest.mark.parametrize("name", ["spring_clear", "winter_cloudy", "spring_restart_in_window"])
def test_replay_deadline_end_time_and_command_count(name):
    for day in _weekend(name).values():
        assert day["reached_62"] is not None and day["reached_62"] < "15:30", day
        assert day["target_after_18_00"] == 45, day
        assert day["commands"] <= 3, day


def test_replay_cloudy_weekend_uses_the_deadline_fallback():
    days = _weekend("spring_cloudy")
    assert {d["opened_by"] for d in days.values()} == {"deadline_fallback"}
