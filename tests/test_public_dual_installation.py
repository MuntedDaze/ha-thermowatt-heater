"""Fresh-install safety, preserving migrations and target-labelled learning."""

from datetime import timedelta
import importlib
import pytest

from test_shadow_model import c, m
from test_simple_policy import MON, MIN, at, sp
from test_integration_0_9_0 import Rig, hobart
from test_measured_performance import power

install = importlib.import_module(f"{m.__package__}.installation")
perf = importlib.import_module(f"{m.__package__}.performance")


def test_fresh_install_does_not_inherit_household_verification():
    settings, _ = c.parse_options({})
    assert not settings.meter_verified and not settings.tariff_verified
    assert c.DEFAULT_OPTIONS["controller_four_state_qualified"] is False
    assert c.DEFAULT_OPTIONS["heater_meter_verification"] == ""
    assert c.DEFAULT_OPTIONS["peak_heating_policy"] == sp.PEAK_NEVER


def test_old_explicit_choices_flags_mappings_and_topics_are_preserved():
    old = {
        "meter_verified": False,
        "tariff_verified": True,
        "import_positive": True,
        "tariff_clock": "local",
        "controller_command_topic": "P/SYNTHETIC/CMD/MODE",
        "forecast_enabled": False,
        "controller_three_state_qualified": True,
    }
    source = {"heater": "water_heater.synthetic", "grid": "sensor.custom_grid", "pv_ac": ""}
    migrated = install.preserve_existing(old, source)
    assert all(migrated[key] == value for key, value in old.items())
    assert migrated["sources"] == source and "pv_ac" not in old
    implicit = install.preserve_existing({}, source)
    assert implicit["meter_verified"] and implicit["tariff_verified"]
    assert implicit["import_positive"] is False and implicit["tariff_clock"] == "standard"
    assert migrated["peak_heating_policy"] == sp.PEAK_NEVER


def test_ct_free_cloud_only_installation_can_do_required_62(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, hobart(MON, 13, 50), reading=40)
    options = {
        **rig.entry.options,
        "normal_storage_c": "62",
        "peak_heating_policy": sp.PEAK_NEVER,
        "meter_verified": False,
    }
    rig.entry.options.update(options)
    rig.sources = {key: value for key, value in rig.sources.items() if key in c.CLOUD_SOURCES}
    rig.runtime.apply_options(options, rig.sources)
    rig.executor.configure(options)
    rig.enable()
    rig.run(hobart(MON, 14, 5))
    assert rig.commands() == ["Manual:62@off"]
    assert rig.runtime.values["circuit_measurement_mode"] == "ct_free"
    assert rig.executor.last_observation.element == "unknown"
    assert rig.runtime.values["measured_pv_ac_kw"] is None


@pytest.mark.parametrize(
    "options",
    [
        {"baseline_c": "46"},
        {"normal_storage_c": "63"},
        {"normal_storage_c": "70", "solar_boost_c": "62"},
        {"tank_litres": 0},
        {"element_kw": 10},
        {"completion_margin_minutes": 1},
    ],
)
def test_configuration_never_authorises_unsupported_values(options):
    with pytest.raises(ValueError):
        c.parse_options(options)


def learn(h, start, target, litres=315, kw=3):
    for i in range(62):
        now = start + i * MIN
        poll = start + (i // 30) * 30 * MIN
        temp = 35 + (poll - start).total_seconds() / 3600 * kw / (litres * 4.186 / 3600)
        h.update(power(now, 0 if i == 61 else kw * 1000), temp, poll, "Manual", target)


def test_learning_62_and_70_are_independent_and_never_relabels_v1_history():
    h = perf.MeasuredHistory()
    for i in range(10):
        learn(h, at(MON, 12) + timedelta(days=i), 62)
    assert h.calibration(62)["ready"] and not h.calibration(70)["ready"]
    assert all(row["target_c"] == 62 for row in h.sessions)
    old = h.to_dict()
    old["version"] = 1
    preserved = perf.MeasuredHistory.from_dict(old)
    assert len(preserved.sessions) == 10 and not preserved.calibration(62)["ready"]
    assert all(row["target_c"] is None and row["legacy_unclassified"] for row in preserved.sessions)


def test_tank_change_and_target_change_cannot_mix_calibration():
    h = perf.MeasuredHistory(200, 2.4)
    learn(h, at(MON, 12), 62, 200, 2.4)
    assert h.sessions[-1]["tank_litres"] == 200
    assert h.sessions[-1]["nominal_kw"] == 2.4
    h.configure(315, 3)
    assert h.calibration(62)["sessions"] == 0
    assert len(h.sessions) == 1  # historical observation preserved, not refitted


def test_completion_62_uses_only_covered_measured_energy_and_reanchors():
    h = perf.MeasuredHistory()
    start = at(MON, 12)
    initial = h.completion(start, 45, start, 62, power(start))
    for i in range(21):
        h.update(power(start + i * MIN), 45, start, "Manual", 62)
    later = h.completion(start + 20 * MIN, 45, start, 62, power(start + 20 * MIN))
    assert later["measured_kwh_since_anchor"] == pytest.approx(1)
    assert later["continuous_minutes_high"] < initial["continuous_minutes_high"]
    assert not later["reported_target_reached"]
