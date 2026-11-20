"""Integration-specific measurement and four-state contract regressions."""

import copy
import pytest

from energy_monitoring.mapping import load, validate
from energy_monitoring.package import build_package
from energy_monitoring.dashboard import build_dashboard, referenced_entities
from energy_template_shim import render
from test_energy_monitoring_templates import entity


@pytest.mark.parametrize("age,valid", [(0, True), (300, True), (301, False), (-1, False)])
def test_stale_numeric_power_is_unavailable_instead_of_integrating_old_draw(age, valid):
    config = load()
    config["circuits"][0]["power"] = "sensor.raw_circuit"
    package = build_package(config)
    for name, source, units in (
        ("EM grid import power", config["grid"]["power"], "W"),
        ("EM hot water power", "sensor.raw_circuit", "kW"),
    ):
        state = {source: {"state": 0, "age": age, "attributes": {"unit_of_measurement": units}}}
        assert render(entity(package, name)["availability"], state) is valid


@pytest.mark.parametrize("value", ["false", 0, None])
def test_meter_direction_requires_a_real_boolean(value):
    config = load()
    config["grid"]["export_positive"] = value
    # load() is normalised (peak minutes), so use the YAML source for validation.
    from test_energy_monitoring_build import raw_map

    raw = raw_map()
    raw["grid"]["export_positive"] = value
    with pytest.raises(ValueError, match="boolean"):
        validate(raw)


def test_duplicate_raw_circuits_cannot_double_count_and_downstream_plug_is_excluded():
    from test_energy_monitoring_build import raw_map
    from energy_monitoring.mapping import tracked_sources

    raw = raw_map()
    raw["circuits"][0]["power"] = raw["circuits"][1]["power"] = "sensor.same_circuit"
    with pytest.raises(ValueError, match="double count"):
        validate(raw)
    raw["circuits"][1]["power"] = ""
    raw["appliances"][0].update(power="sensor.same_circuit", circuit="hot_water")
    config = validate(raw)
    assert not any(s["key"] == raw["appliances"][0]["key"] for s in tracked_sources(config))


def test_dashboard_maps_four_state_and_prediction_contract_without_ct_dependency():
    config = load()
    refs = referenced_entities(build_dashboard(config))
    for key in (
        "baseline_target",
        "normal_target",
        "boost_target",
        "desired_temperature",
        "heating_requirement",
        "peak_policy",
        "boost_reason",
        "measurement_mode",
        "expected_completion",
        "next_poll",
        "request_budget",
    ):
        assert config["hot_water"][key] in refs
    assert not any(ref.startswith("sensor.em_hot_water_power") for ref in refs)
    changed = copy.deepcopy(config)
    changed["circuits"][1]["power"] = "sensor.optional_ac"
    assert changed["hot_water"] == config["hot_water"]
