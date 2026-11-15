"""Combined tariffs have one authority; missing hardware never invents readings."""

from copy import deepcopy

import pytest

from energy_monitoring.mapping import load, validate
from energy_monitoring.package import build_package
from energy_template_shim import changed, previous, render
from test_energy_monitoring_templates import entity, run_accumulator


@pytest.mark.parametrize(
    "period,price", [("off_peak", 0.17), ("shoulder", 0.12), ("peak", 0.36), ("off_peak", 0)]
)
def test_combined_prices_follow_verified_controller_windows(period, price):
    config = load()
    hw = config["hot_water"]
    states = {
        hw["current_tariff"]: period,
        hw["import_price"]: price,
        hw["feed_in_price"]: 0,
        hw["tariff_verification"]: "verified",
    }
    built = build_package(config)
    for name, expected in (
        ("EM tariff period", period),
        ("EM import price", price),
        ("EM feed in price", 0),
    ):
        sensor = entity(built, name)
        assert render(sensor["availability"], states) is True
        assert render(sensor["state"], states) == expected
    states[hw["tariff_verification"]] = "unverified"
    for name in ("EM tariff period", "EM import price", "EM feed in price"):
        assert render(entity(built, name)["availability"], states) is False


def test_real_zero_rate_is_distinct_from_missing_price():
    sensor = entity(build_package(load()), "EM grid import cost")

    def prices(index):
        return {
            "sensor.em_import_price": {
                "state": 0 if index < 2 else "unavailable",
                "attributes": {"zero_rate_verified": index < 2},
            }
        }

    total, attributes = run_accumulator(sensor, [10, 11, 12], prices)
    assert total == 0
    assert attributes["unpriced_kwh"] == 1  # only missing-price energy
    # An unverified zero helper is not a free-electricity contract.
    _, attributes = run_accumulator(sensor, [10, 11], lambda _: {"sensor.em_import_price": 0})
    assert attributes["unpriced_kwh"] == 1


def test_shoulder_is_preserved_as_a_separate_import_total():
    sensor = entity(build_package(load()), "EM grid import shoulder energy")
    total, _ = run_accumulator(
        sensor,
        [10, 11, 12],
        lambda n: {"sensor.em_tariff_period": ("peak", "shoulder", "off_peak")[n]},
    )
    assert total == 1


def test_missing_inputs_are_unavailable_and_unmeasured_totals_do_not_start_at_zero():
    config = deepcopy(load())
    for group in ("grid", "solar", "house"):
        for key, value in config[group].items():
            if isinstance(value, str):
                config[group][key] = ""
    config["appliances"] = []
    built = build_package(config)
    for name in (
        "EM grid import power",
        "EM grid export power",
        "EM solar power",
        "EM house power",
    ):
        assert render(entity(built, name)["availability"], {}) is False
    sensor = entity(built, "EM grid import cost")
    assert (
        render(sensor["availability"], {}, this=previous(), trigger=changed("unavailable")) is False
    )
    assert (
        render(
            sensor["availability"],
            {},
            this=previous(last_reading=12),
            trigger=changed("unavailable"),
        )
        is True
    )


def test_controller_tariff_mapping_cannot_be_partial():
    import yaml
    from energy_monitoring.mapping import DEFAULT_MAP

    raw = yaml.safe_load(DEFAULT_MAP.read_text(encoding="utf-8"))
    raw["hot_water"]["import_price"] = ""
    with pytest.raises(ValueError, match="verification mappings required"):
        validate(raw)
