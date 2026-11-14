"""Synthetic circuit inputs; no brand, hardware or cloud assumptions."""

from datetime import timedelta
import importlib

import pytest
from test_integration_0_9_0 import Rig, hobart

from test_shadow_model import m
from test_simple_policy import MIN, MON, OFF, S, STORE, TARIFFS, at, snap, sp

meter = importlib.import_module(f"{m.__package__}.measurement")
NOW = at(MON, 9)
ENTITY = "sensor.generic_hws"


@pytest.fixture
def rig(tmp_path, monkeypatch):
    return Rig(tmp_path, monkeypatch, hobart(MON, 11))


def read(value, unit="W", **changes):
    args = {"value": value, "unit": unit, "observed_at": NOW, **changes}
    return meter.circuit_power(m.Reading(**args), ENTITY, f"{ENTITY}|{unit}", NOW, NOW - MIN)


@pytest.mark.parametrize(
    "value,unit,state,watts",
    [(0, "W", "off", 0), (30, "W", "off", 30), (2700, "W", "on", 2700), (3.1, "kW", "on", 3100)],
)
def test_normalize_valid_circuit_power(value, unit, state, watts):
    result = read(value, unit)
    assert result.valid and (result.state, result.watts) == (state, watts)


@pytest.mark.parametrize(
    "value,unit",
    [
        (-3000, "W"),
        (1500, "W"),
        (4800, "W"),
        ("nan", "W"),
        ("inf", "W"),
        (True, "W"),
        (3, "kWh"),
        ("unknown", "W"),
        ("unavailable", "W"),
    ],
)
def test_false_or_implausible_circuit_readings_are_unknown(value, unit):
    result = read(value, unit)
    assert not result.valid and result.state == "unknown"


@pytest.mark.parametrize(
    "changes",
    [
        {"restored": True},
        {"observed_at": NOW + MIN},
        {"observed_at": NOW - timedelta(minutes=3)},
        {"observed_at": NOW.replace(tzinfo=None)},
    ],
)
def test_stale_future_restored_and_preboot_reports_are_unknown(changes):
    assert not read(3000, **changes).valid


def test_verification_is_bound_to_entity_and_unit():
    reading = m.Reading(3, NOW, "kW")
    for stamp in ("", "sensor.old|kW", f"{ENTITY}|W"):
        assert not meter.circuit_power(reading, ENTITY, stamp, NOW, NOW - MIN).valid


def test_reversed_ct_sign_is_preserved_for_commissioning_diagnostics():
    result = read(-3000)
    assert result.watts == -3000 and not result.valid and result.state == "unknown"


def test_steady_zero_requires_real_republication_not_repeated_evaluation():
    reading = m.Reading(0, NOW, "W")
    for second, valid in [(0, True), (120, True), (121, False), (300, False)]:
        result = meter.circuit_power(
            reading, ENTITY, f"{ENTITY}|W", NOW + timedelta(seconds=second), NOW - MIN
        )
        assert result.valid is valid
    recovered = meter.circuit_power(
        m.Reading(0, NOW + 5 * MIN, "W"), ENTITY, f"{ENTITY}|W", NOW + 5 * MIN, NOW - MIN
    )
    assert recovered.valid and recovered.state == "off"


def test_dashboard_absolute_power_wrapper_cannot_qualify_control():
    result = meter.circuit_power(
        m.Reading(0, NOW, "W"),
        "sensor.em_hot_water_power",
        "sensor.em_hot_water_power|W",
        NOW,
        NOW - MIN,
    )
    assert result.quality == "wrapper_not_raw_meter" and not result.valid


def test_steady_zero_runtime_loss_is_visible_and_does_not_contact_cloud(rig):
    rig.report("sensor.synthetic_heater_w", 0, {"unit_of_measurement": "W"})
    rig.runtime.update(rig.now())
    assert rig.runtime.circuit.valid
    initial = rig.bridge.usage.total
    rig.t += 121
    rig.runtime.update(rig.now())
    assert not rig.runtime.circuit.valid and rig.runtime.circuit.state == "unknown"
    assert any("report_cadence" in warning for warning in rig.runtime.warnings)
    assert rig.bridge.usage.total == initial and not rig.posts


@pytest.mark.parametrize(
    "grid,heater,available,solar,imported",
    [
        (0.12, 2.72, 2.60, 2.60, 0.12),
        (3.5, 3, -0.5, 0, 3),
        (-0.1, 0, 0.1, 0, 0),
        (-1, 2.7, 3.7, 2.7, 0),
    ],
)
def test_power_conservation_uses_exact_watts(grid, heater, available, solar, imported):
    budget = meter.power_balance(grid, heater)
    assert budget["available_before_heater_kw"] == pytest.approx(available)
    assert budget["heater_solar_kw"] == pytest.approx(solar)
    assert budget["heater_grid_kw"] == pytest.approx(imported)
    assert budget["grid_without_heater_kw"] + heater == pytest.approx(grid)


def test_duplicate_reports_do_not_vote_and_loss_requires_full_requalification():
    p = sp.SimplePolicy(S, TARIFFS)
    for _ in range(100):
        p.add_meter(NOW, -4, heater_kw=0)
    assert len(p.samples) == 1
    assert not p.decide(snap(NOW, OFF)).command
    for i in range(1, 11):
        p.add_meter(NOW + i * MIN, -4, heater_kw=0)
    assert p.decide(snap(NOW + 10 * MIN, OFF)).command == "Manual:70"
    assert p.decide(snap(NOW + 10 * MIN, OFF, heater_meter_valid=False)).command is None
    assert p.decide(snap(NOW + 10 * MIN, STORE, heater_meter_valid=False)).command == "off"


def test_ct_outage_preserves_weekday_essential_heat():
    d = sp.SimplePolicy(S, TARIFFS).decide(
        snap(at(MON, 15), OFF, reading=40, heater_meter_valid=False)
    )
    assert d.command == "Manual:70"


def test_selected_70_and_cloud_bit_cannot_override_idle_ct(rig):
    rig.report("sensor.synthetic_heater_w", 0, {"unit_of_measurement": "W"})
    rig.runtime.update(rig.now())
    assert rig.runtime.circuit.state == "off"
    rig.executor.controller.heater = STORE
    rig.executor.controller.state = "storage_70"
    rig.executor.controller.enabled = True
    rig.executor.decide(rig.now(), rig.executor.observe(rig.now()))
    assert rig.executor.policy.samples[-1][3] is False


def test_mapped_ct_unavailable_never_falls_back_to_aggregate(rig):
    rig.report("sensor.synthetic_heater_w", "unavailable", {"unit_of_measurement": "W"})
    rig.runtime.update(rig.now())
    assert not rig.runtime.circuit.valid and rig.runtime.power_budget is None
    rig.executor.decide(rig.now(), rig.executor.observe(rig.now()))
    assert not rig.executor.policy.samples
