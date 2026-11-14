"""Read-only metered heating calibration: real kWh and conservative data gaps."""

from datetime import timedelta
import importlib

import pytest

from test_controller_0_9_0 import local, m

thermal = importlib.import_module(f"{m.__package__}.thermal")


def test_verified_ct_integrates_actual_watts_not_nominal_three_kw():
    obs = thermal.ThermalObserver()
    start = local(hour=11)
    obs.update(start, 45, start, "off", "verified", "Manual", heater_power_kw=0, meter_configured=True)
    for minute in range(1, 121):
        at = start + timedelta(minutes=minute)
        reading_at = at if minute % 30 == 0 else start + timedelta(minutes=(minute // 30) * 30)
        temp = 45 + round(minute / 120 * 17)
        obs.update(
            at, temp, reading_at, "on", "verified", "Manual",
            heater_power_kw=2.6, meter_configured=True,
        )
    done = start + timedelta(minutes=121)
    obs.update(done, 63, done, "off", "verified", "Manual", heater_power_kw=0, meter_configured=True)
    assert len(obs.sessions) == 1
    session = obs.sessions[0]
    assert session["energy_source"] == "circuit_meter"
    assert session["meter_gap"] is False
    assert session["energy_kwh"] == pytest.approx(5.2, abs=0.09)
    assert session["observed_c_per_kwh"] > 0
    summary = obs.summary(done)["inferred"]["metered_heating_undisturbed"]
    assert summary["sessions"] == 1


def test_meter_outage_excludes_incomplete_session_from_training():
    obs = thermal.ThermalObserver()
    start = local(hour=12)
    obs.update(start, 45, start, "off", "verified", "Manual", heater_power_kw=0, meter_configured=True)
    for minute in range(1, 32):
        at = start + timedelta(minutes=minute)
        obs.update(
            at, 48 if minute >= 30 else 45,
            start + timedelta(minutes=30) if minute >= 30 else start,
            "on", "verified", "Manual", heater_power_kw=2.8, meter_configured=True,
        )
    lost = start + timedelta(minutes=32)
    obs.update(lost, 48, start + timedelta(minutes=30), "unknown", "low", "Manual",
               heater_power_kw=None, meter_configured=True)
    end = start + timedelta(minutes=60)
    obs.update(end, 53, end, "off", "verified", "Manual", heater_power_kw=0, meter_configured=True)
    assert len(obs.sessions) == 1
    assert obs.sessions[0]["meter_gap"] is True
    assert "observed_c_per_kwh" not in obs.sessions[0]
    assert obs.summary(end)["inferred"]["metered_heating_undisturbed"] is None
