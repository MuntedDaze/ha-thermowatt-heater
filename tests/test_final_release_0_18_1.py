"""Controller 0.18.1: forecast independence and policy-aligned recovery.

Final owner instruction, 20 November 2026 (docs/OPERATING_POLICY.md):
forecasts are an optional optimisation input; they never authorise a 70 °C
boost, their loss never stops required heating, and measured surplus alone can
still qualify a boost.
"""

import importlib
from pathlib import Path

import pytest

from test_dual_storage_policy import D, NORMAL, sun
from test_shadow_model import m
from test_simple_policy import MIN, MON, OFF, SAT, STORE, TARIFFS, at, fc, snap, sp

ROOT = Path(__file__).parents[1]
ctl = importlib.import_module(f"{m.__package__}.controller")
forecast = importlib.import_module(f"{m.__package__}.forecast")


@pytest.mark.parametrize("state,reading", [(OFF, 45), (NORMAL, 54)])
def test_measured_surplus_alone_qualifies_a_boost_without_any_forecast(state, reading):
    now = at(MON, 12)
    p = sp.SimplePolicy(D, TARIFFS)
    sun(p, now)  # 10 minutes of 4 kW measured export (>= 3.3 kW)
    d = p.decide(snap(now, state, reading=reading, forecast=()))
    assert d.state == STORE and d.command == "Manual:70", d.reason
    assert d.plan["boost_eligible"]


def test_a_forecast_never_authorises_a_boost_without_measured_surplus():
    now = at(MON, 12)
    p = sp.SimplePolicy(D, TARIFFS)
    for i in range(11):
        p.add_meter(now - (10 - i) * MIN, 0.4, heater_kw=0)  # importing, not exporting
    d = p.decide(snap(now, OFF, reading=45, forecast=fc(now, 6, 5)))
    assert d.state != STORE and not d.plan["boost_eligible"]
    assert d.plan["boost_reason"] == "sustained_full_solar_required"


def test_no_measurement_suspends_solar_permission_and_never_invents_surplus():
    now = at(MON, 12)
    p = sp.SimplePolicy(D, TARIFFS)  # no meter samples at all
    d = p.decide(snap(now, OFF, reading=45, forecast=fc(now, 6, 5)))
    assert d.state != STORE
    assert d.plan["boost_reason"] in {
        "verified_circuit_and_grid_required",
        "sustained_full_solar_required",
    }


@pytest.mark.parametrize("hour", [11, 13, 15])
def test_weekday_required_62_needs_no_forecast(hour):
    now = at(MON, hour)
    p = sp.SimplePolicy(D, TARIFFS)
    d = p.decide(snap(now, OFF, reading=35, heater_meter_valid=False, forecast=()))
    # Either already started or held until the latest start; never abandoned.
    assert d.plan["mode"] == "deadline" and d.plan["latest_start"] is not None
    if now >= d.plan["latest_start"]:
        assert d.state == NORMAL and d.command == "Manual:62"


def test_weekend_window_without_forecast_starts_62_at_once():
    now = at(SAT, 9)
    p = sp.SimplePolicy(D, TARIFFS)
    for i in range(3):
        p.add_pv(now - (2 - i) * MIN, 1.0)
    d = p.decide(snap(now, sp.BASELINE, reading=40, heater_meter_valid=False, forecast=()))
    assert d.state == NORMAL and d.command == "Manual:62"


def test_recovery_guidance_returns_to_the_policy_not_native_schedule():
    text = ctl.RECOVERY["unexpected_mode_or_target"]
    assert "Manual 45 °C overnight" in text and "weekend comfort window" in text
    assert "Resume automatic control" in text
    docs = (ROOT / "thermowatt-heater/DOCS.md").read_text(encoding="utf-8")
    assert "Back to your normal programme: **Schedule**" not in docs
    assert "Resume automatic control" in docs


def test_only_the_emhass_forecast_series_and_the_conservative_floor_remain():
    assert not hasattr(forecast, "_flat_load")
    source = (ROOT / "custom_components/thermann_shadow/forecast.py").read_text(encoding="utf-8")
    assert '"watts"' not in source and "age_coverage_ratio" not in source
    assert forecast.FALLBACK_LOAD_KW == 1.0
