"""Generic hot-water CT power: measured watts, freshness, and fail-closed solar.

All tests are synthetic and offline. No Shelly model or live HA device is required.
"""

import math

import pytest

from test_integration_0_9_0 import Rig, c, hobart
from test_simple_policy import BASE, MIN, OFF, S, STORE, TARIFFS, at, feed, snap, sp


def test_measured_heater_watts_override_nominal_estimate():
    p = sp.SimplePolicy(S, TARIFFS)
    now = at(16, 9)
    p.add_meter(now, 0.25, True, measured_heater_kw=2.72)
    assert p.samples[-1][2] == pytest.approx(2.47)
    assert p.samples[-1][3] is True

    p.add_meter(now + MIN, 0.25, True, measured_heater_kw=0.0)
    assert p.samples[-1][2] == pytest.approx(-0.25)
    assert p.samples[-1][3] is False

    p.add_meter(now + 2 * MIN, 0.25, False, measured_heater_kw=2.86)
    assert p.samples[-1][2] == pytest.approx(2.61)
    assert p.samples[-1][3] is True


@pytest.mark.parametrize("value", [-0.1, 4.5, math.nan, math.inf])
def test_measured_heater_power_is_validated(value):
    p = sp.SimplePolicy(S, TARIFFS)
    with pytest.raises(ValueError, match="heater_power_out_of_range"):
        p.add_meter(at(16, 9), 0.0, True, measured_heater_kw=value)
    assert not p.samples


def test_peak_ct_outage_issues_protective_off_despite_recent_start():
    p = sp.SimplePolicy(S, TARIFFS)
    now = at(16, 9)
    p.add_meter(now, 0.1, False)
    d = p.decide(snap(now, STORE, last_command_at=now - 2 * MIN, heater_power_ready=False))
    assert (d.state, d.reason, d.command) == (
        OFF,
        "peak_heater_power_unavailable",
        "off",
    )


def test_ct_outage_prevents_new_optional_solar_but_not_essential_storage():
    p = sp.SimplePolicy(S, TARIFFS)
    now = feed(p, at(14, 11), 12, -4.0)
    d = p.decide(snap(now, BASE, reading=45, heater_power_ready=False))
    assert (d.state, d.command) == (BASE, None)

    weekday = at(16, 16)
    q = sp.SimplePolicy(S, TARIFFS)
    d = q.decide(snap(weekday, BASE, reading=40, heater_power_ready=False))
    assert (d.state, d.command) == (STORE, "Manual:70")


def test_runtime_reads_generic_power_sensor_and_drops_stale_values(tmp_path, monkeypatch):
    rig = Rig(
        tmp_path,
        monkeypatch,
        hobart(16, 9),
        reading=52,
        mode="Manual",
        setpoint=70,
        pv=lambda loc: 3.8,
    )
    source = "sensor.hot_water_ct_power"
    rig.sources["heater_power"] = source
    rig.report(source, 2980, {"unit_of_measurement": "W"})
    rig.report(c.DEFAULT_SOURCES["grid"], -400, {"unit_of_measurement": "W"})
    rig.runtime.update(rig.now())
    assert rig.runtime.heater_power_kw == pytest.approx(2.98)
    assert rig.runtime.heater.state == "on"
    assert rig.runtime.heater.confidence == "verified"
    assert rig.runtime.values["heater_power_source_ready"] is True

    observation = rig.executor.observe(rig.now())
    rig.executor.decide(rig.now(), observation)
    assert rig.executor.policy.samples[-1][2] == pytest.approx(2.58)

    # A later CT outage cannot fall back to an inferred 3 kW solar credit.
    rig.t += 121
    rig._meter()
    rig.runtime.update(rig.now())
    assert rig.runtime.heater_power_kw is None
    assert rig.runtime.values["heater_power_source_ready"] is False
    observation = rig.executor.observe(rig.now())
    rig.executor.decide(rig.now(), observation)
    assert rig.executor.policy.samples[-1][3] is False


@pytest.mark.parametrize("power_w", [-2980, 5000])
def test_bad_ct_polarity_or_shared_circuit_is_rejected(tmp_path, monkeypatch, power_w):
    rig = Rig(tmp_path, monkeypatch, hobart(16, 9), mode="Manual", setpoint=70)
    rig.sources["heater_power"] = "sensor.hot_water_ct_power"
    rig.report(
        "sensor.hot_water_ct_power",
        power_w,
        {"unit_of_measurement": "W"},
    )
    rig.runtime.update(rig.now())
    assert rig.runtime.heater_power_kw is None
    assert "heater_power_implausible_check_ct_circuit" in rig.runtime.warnings
