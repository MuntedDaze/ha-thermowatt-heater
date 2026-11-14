"""Render the generated package's templates offline and compare with calc.py."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from energy_monitoring import calc  # noqa: E402
from energy_monitoring.mapping import DEFAULT_MAP, load, validate  # noqa: E402
from energy_monitoring.package import build_package  # noqa: E402
from energy_template_shim import changed, previous, render  # noqa: E402

HOBART = ZoneInfo("Australia/Hobart")
GRID = "sensor.goodwe_inverter_meter_active_power"
RATES = {
    "input_number.em_peak_rate": 0.36,
    "input_number.em_off_peak_rate": 0.17,
    "input_number.em_feed_in_rate": 0.09,
    "input_number.em_daily_supply_charge": 1.2,
}


def with_meters(**changes):
    """The default map with all three CTs mapped (synthetic entity IDs)."""
    import yaml

    raw = yaml.safe_load(DEFAULT_MAP.read_text(encoding="utf-8"))
    for circuit in raw["circuits"]:
        circuit["power"] = f"sensor.ct_{circuit['key']}_power"
    raw.update(changes)
    return validate(raw)


def entity(package, name):
    for block in package["template"]:
        for kind in ("sensor", "binary_sensor"):
            for item in block.get(kind, []):
                if item["name"] == name:
                    return item
    raise KeyError(name)


@pytest.fixture(scope="module")
def package():
    return build_package(with_meters())


@pytest.mark.parametrize("power", [-2400.0, 0.0, 1800.5, 5000.0])
@pytest.mark.parametrize("export_positive", [True, False])
def test_grid_power_is_split_by_the_configured_sign(power, export_positive):
    config = with_meters()
    config["grid"]["export_positive"] = export_positive
    built = build_package(config)
    states = {GRID: power}
    expected = calc.split_grid(power, export_positive)
    assert render(entity(built, "EM grid import power")["state"], states) == expected[0]
    assert render(entity(built, "EM grid export power")["state"], states) == expected[1]


@pytest.mark.parametrize("state", ["unavailable", "unknown", "", "nan"])
def test_an_unusable_reading_makes_the_sensor_unavailable_not_zero(package, state):
    assert render(entity(package, "EM grid import power")["availability"], {GRID: state}) is False
    assert render(entity(package, "EM grid import power")["availability"], {GRID: 12}) is True


def test_solar_can_be_treated_as_zero_when_the_inverter_sleeps():
    config = with_meters()
    config["solar"]["zero_when_unavailable"] = True
    solar = entity(build_package(config), "EM solar power")
    assert "availability" not in solar
    assert render(solar["state"], {"sensor.goodwe_inverter_pv_power": "unavailable"}) == 0


# Hobart daylight saving: starts Sun 4 Oct 2026, ends Sun 4 Apr 2027.
TARIFF_MOMENTS = [
    datetime(2026, 11, 16, 6, 59, tzinfo=timezone(timedelta(hours=10))),  # Monday
    datetime(2026, 11, 16, 7, 0, tzinfo=timezone(timedelta(hours=10))),
    datetime(2026, 11, 16, 9, 59, tzinfo=timezone(timedelta(hours=10))),
    datetime(2026, 11, 16, 10, 0, tzinfo=timezone(timedelta(hours=10))),
    datetime(2026, 11, 16, 16, 0, tzinfo=timezone(timedelta(hours=10))),
    datetime(2026, 11, 16, 20, 59, tzinfo=timezone(timedelta(hours=10))),
    datetime(2026, 11, 16, 21, 0, tzinfo=timezone(timedelta(hours=10))),
    datetime(2026, 11, 14, 8, 0, tzinfo=timezone(timedelta(hours=10))),  # Saturday
    datetime(2026, 11, 16, 7, 30, tzinfo=HOBART),  # 06:30 AEST: still off-peak
    datetime(2026, 11, 16, 8, 0, tzinfo=HOBART),  # 07:00 AEST: peak begins
    datetime(2026, 10, 4, 1, 59, tzinfo=HOBART),  # the night the clocks go forward
    datetime(2026, 10, 5, 7, 30, tzinfo=HOBART),
    datetime(2027, 4, 4, 2, 30, tzinfo=HOBART),  # the repeated hour
    datetime(2027, 4, 5, 7, 30, tzinfo=HOBART),  # standard time again: peak
    datetime(2026, 11, 15, 23, 30, tzinfo=timezone.utc),  # Monday 09:30 AEST
]


@pytest.mark.parametrize("moment", TARIFF_MOMENTS)
@pytest.mark.parametrize("clock", ["standard", "local"])
def test_tariff_period_matches_the_reference_through_daylight_saving(moment, clock):
    config = with_meters()
    config["tariff"]["clock"] = clock
    local = moment.astimezone(HOBART)  # Home Assistant's now() is local time
    state = entity(build_package(config), "EM tariff period")["state"]
    assert render(state, now=local) == calc.tariff_period(local, config["tariff"])


def test_tariff_93_is_fixed_standard_time():
    tariff = with_meters()["tariff"]
    summer = datetime(2026, 11, 16, 7, 30, tzinfo=HOBART)
    assert calc.tariff_period(summer, tariff) == "off_peak"  # 06:30 AEST
    assert calc.tariff_period(summer + timedelta(minutes=30), tariff) == "peak"
    assert calc.tariff_period(datetime(2026, 7, 13, 7, 0, tzinfo=HOBART), tariff) == "peak"
    with pytest.raises(ValueError):
        calc.tariff_period(datetime(2026, 7, 13, 7, 0), tariff)


def test_import_price_follows_the_period_and_needs_both_rates(package):
    price = entity(package, "EM import price")
    assert render(price["state"], {**RATES, "sensor.em_tariff_period": "peak"}) == 0.36
    assert render(price["state"], {**RATES, "sensor.em_tariff_period": "off_peak"}) == 0.17
    assert render(price["availability"], RATES) is True
    assert render(price["availability"], {**RATES, "input_number.em_peak_rate": 0}) is False
    assert render(price["availability"], {}) is False  # helpers not created yet


def run_accumulator(sensor, readings, states_for):
    """Feed meter readings through the template; return (total, attributes)."""
    this = None
    for index, reading in enumerate(readings):
        variables = {"this": this, "trigger": changed(reading)}
        states = states_for(index)
        state = render(sensor["state"], states, **variables)
        attributes = {
            key: render(template, states, **variables)
            for key, template in sensor["attributes"].items()
        }
        this = previous(state, **attributes)
    return float(this.state), this.attributes


READINGS = [
    100.0,  # first reading: baseline only
    100.5,
    "unavailable",  # the gap must not lose the energy that follows
    "unknown",
    101.5,
    101.5,  # attribute-only update
    30.0,  # meter replaced or reset: re-baseline
    30.4,
    9999.0,  # glitch: ignored
    9999.2,
]


def test_cost_accumulator_matches_the_reference(package):
    sensor = entity(package, "EM grid import cost")
    prices = [0.17, 0.17, 0.17, 0.17, 0.36, 0.36, 0.36, 0.17, 0.17, "unavailable"]
    reference = calc.Accumulator()
    for reading, price in zip(READINGS, prices, strict=True):
        reference.update(reading, price if isinstance(price, float) else 0.0)
    total, attributes = run_accumulator(
        sensor, READINGS, lambda index: {"sensor.em_import_price": prices[index]}
    )
    # 0.5 kWh at 0.17, 1.0 at 0.36 (across the gap), 0.4 at 0.17; 0.2 unpriced.
    assert total == pytest.approx(0.5 * 0.17 + 1.0 * 0.36 + 0.4 * 0.17, abs=1e-4)
    assert total == pytest.approx(reference.total, abs=1e-4)
    assert attributes["last_reading"] == reference.last_reading == 9999.2
    assert attributes["unpriced_kwh"] == pytest.approx(reference.unpriced) == pytest.approx(0.2)


def test_a_later_rate_change_does_not_reprice_earlier_energy(package):
    sensor = entity(package, "EM grid export earnings")
    total, _ = run_accumulator(
        sensor,
        [10.0, 11.0, 12.0],
        lambda index: {"sensor.em_feed_in_price": [0.09, 0.09, 0.05][index]},
    )
    assert total == pytest.approx(0.09 + 0.05)


def test_import_energy_is_split_between_peak_and_off_peak(package):
    periods = ["off_peak", "off_peak", "peak", "peak", "off_peak", "unknown"]
    readings = [50.0, 51.0, 51.5, 53.5, 53.75, 54.0]
    totals = {}
    for name in ("EM grid import peak energy", "EM grid import off peak energy"):
        totals[name], _ = run_accumulator(
            entity(package, name),
            readings,
            lambda index: {"sensor.em_tariff_period": periods[index]},
        )
    assert totals["EM grid import peak energy"] == pytest.approx(2.5)
    assert totals["EM grid import off peak energy"] == pytest.approx(1.25)


def test_accumulator_survives_a_missing_previous_state(package):
    sensor = entity(package, "EM grid import cost")
    states = {"sensor.em_import_price": 0.2}
    assert render(sensor["state"], states, this=None, trigger=changed(5)) == 0
    assert render(sensor["state"], states, this=previous("unknown"), trigger=changed(5)) == 0
    restored = previous(1.25, last_reading=5.0, unpriced_kwh=0)
    assert render(sensor["state"], states, this=restored, trigger=changed(6)) == 1.45


@pytest.mark.parametrize(
    "load,grid_import",
    [(3000, 0), (3000, 3000), (3000, 1200), (3000, 4500), (0, 800), (2950.4, 310.2)],
)
def test_hot_water_is_attributed_marginally(package, load, grid_import):
    states = {"sensor.em_hot_water_power": load, "sensor.em_grid_import_power": grid_import}
    from_grid, from_solar = calc.attribute_load(load, grid_import)
    rendered_grid = render(entity(package, "EM hot water grid power")["state"], states)
    rendered_solar = render(entity(package, "EM hot water solar power")["state"], states)
    assert rendered_grid == pytest.approx(from_grid, abs=0.05)
    assert rendered_solar == pytest.approx(from_solar, abs=0.05)
    assert rendered_grid + rendered_solar == pytest.approx(load, abs=0.1)


def test_a_reversed_ct_clamp_still_reads_as_consumption(package):
    power = entity(package, "EM hot water power")
    assert render(power["state"], {"sensor.ct_hot_water_power": -2987.3}) == 2987.3
    element = entity(package, "EM hot water element on")
    assert render(element["state"], {"sensor.em_hot_water_power": 2987}) is True
    assert render(element["state"], {"sensor.em_hot_water_power": 40}) is False


def test_untracked_is_house_minus_non_overlapping_loads():
    config = with_meters()
    config["appliances"][0]["circuit"] = "oven"  # the dryer plug now sits behind the oven CT
    built = build_package(config)
    tracked = entity(built, "EM tracked power")
    assert "sensor.dryer_current_consumption" not in tracked["state"]
    states = {
        "sensor.em_hot_water_power": 3000,
        "sensor.em_air_conditioner_power": 900,
        "sensor.em_oven_power": 2100,
        "sensor.dryer_current_consumption": 2000,  # inside the oven circuit: not added
        "sensor.washing_machine_current_consumption": 450,
        "sensor.dishwasher_current_consumption": "unavailable",  # counts as nothing
    }
    total = render(tracked["state"], states)
    assert total == 3000 + 900 + 2100 + 450
    assert render(tracked["attributes"]["sources_available"], states) == 4
    states.update({"sensor.em_house_power": 7000, "sensor.em_tracked_power": total})
    sensor = entity(built, "EM untracked power")
    expected, residual = calc.untracked(7000, [3000, 900, 2100, 450])
    assert render(sensor["state"], states) == expected == 550
    assert render(sensor["attributes"]["raw_residual_w"], states) == residual
    states["sensor.em_house_power"] = 6000  # misaligned readings: clamp, but expose it
    assert render(sensor["state"], states) == 0
    assert render(sensor["attributes"]["raw_residual_w"], states) == -450


def test_a_plug_behind_an_unmapped_circuit_still_counts():
    config = load()  # default map: no CT installed
    config["appliances"][0]["circuit"] = "oven"
    tracked = entity(build_package(config), "EM tracked power")
    assert "sensor.dryer_current_consumption" in tracked["state"]


@pytest.mark.parametrize(
    "imported,solar,exported",
    [(12.0, 30.0, 18.0), (5.0, 0.0, 0.0), (0.0, 10.0, 4.0), (0.0, 0.0, 0.0), (3.0, 2.0, 2.5)],
)
def test_daily_ratios_match_the_reference(package, imported, solar, exported):
    states = {
        "sensor.em_grid_import_daily": imported,
        "sensor.em_solar_daily": solar,
        "sensor.em_grid_export_daily": exported,
    }
    house = render(entity(package, "EM house energy today")["state"], states)
    assert house == pytest.approx(calc.house_energy(imported, solar, exported), abs=0.01)
    for name, expected in (
        ("EM self consumption today", calc.self_consumption_percent(solar, exported)),
        ("EM self sufficiency today", calc.self_sufficiency_percent(imported, solar, exported)),
    ):
        value = render(entity(package, name)["state"], states)
        assert value == (None if expected is None else pytest.approx(expected, abs=0.05))


def test_net_cost_includes_the_supply_charge(package):
    states = {
        **RATES,
        "sensor.em_grid_import_cost_daily": 4.2,
        "sensor.em_grid_export_earnings_daily": 1.1,
        "sensor.em_grid_import_cost_monthly": 60.0,
        "sensor.em_grid_export_earnings_monthly": 21.0,
    }
    today = render(entity(package, "EM net energy cost today")["state"], states)
    assert today == pytest.approx(calc.net_cost(4.2, 1.1, 1.2))
    now = datetime(2026, 11, 16, 12, 0, tzinfo=HOBART)
    month = render(entity(package, "EM net energy cost this month")["state"], states, now)
    assert month == pytest.approx(calc.net_cost(60.0, 21.0, 1.2, days=16))


def health_states(now_age=10):
    states = {
        GRID: {"state": 100, "age": now_age},
        "sensor.goodwe_inverter_meter_total_energy_import": 1,
        "sensor.goodwe_inverter_meter_total_energy_export": 1,
        "sensor.goodwe_inverter_house_consumption": {"state": 500, "age": 10},
        "sensor.goodwe_inverter_pv_power": {"state": 0, "age": 10},
        "sensor.em_tariff_period": "peak",
        "sensor.thermann_shadow_current_tariff": "peak",
        **RATES,
    }
    config = with_meters()
    for circuit in config["circuits"]:
        states[circuit["power"]] = {"state": 0, "age": 5}
    for appliance in config["appliances"]:
        states[appliance["power"]] = {"state": 3, "age": 60}
        states[appliance["energy"]] = 0.1
    return states


def test_health_reports_ok_missing_stale_and_unset_rates(package):
    health = entity(package, "EM monitoring health")
    quality = entity(package, "EM monitoring quality")
    states = health_states()
    assert render(health["state"], states) == "ok"
    assert render(health["attributes"]["missing"], states) == []
    assert render(quality["state"], states) == 100
    assert render(health["attributes"]["tariff_matches_controller"], states) is True

    states["sensor.dryer_current_consumption"] = "unavailable"
    states["sensor.ct_oven_power"]["age"] = 301
    del states["sensor.jrig_today_s_consumption"]  # an entity that does not exist
    assert render(health["state"], states) == "degraded"
    assert render(health["attributes"]["missing"], states) == ["Dryer power", "Jrig energy"]
    assert render(health["attributes"]["stale"], states) == ["Oven circuit power"]
    total = int(health["attributes"]["monitored"])
    assert render(quality["state"], states) == pytest.approx(100 * (total - 3) / total, abs=0.05)

    stale_core = health_states(now_age=301)
    assert render(health["state"], stale_core) == "critical"
    unset = {**health_states(), "input_number.em_feed_in_rate": 0}
    assert render(health["state"], unset) == "degraded"
    assert render(health["attributes"]["rates_set"], unset) is False
    mismatch = {**health_states(), "sensor.thermann_shadow_current_tariff": "off_peak"}
    assert render(health["attributes"]["tariff_matches_controller"], mismatch) is False
    offline = {**health_states(), "sensor.thermann_shadow_current_tariff": "unavailable"}
    assert render(health["attributes"]["tariff_matches_controller"], offline) is None


def test_a_heating_cycle_is_captured_between_element_on_and_off(package):
    start_sensor = entity(package, "EM hot water cycle start")
    last_sensor = entity(package, "EM hot water last cycle")
    began = datetime(2026, 11, 16, 1, 0, tzinfo=timezone.utc)
    ended = began + timedelta(minutes=96)
    at_start = {
        "sensor.em_hot_water_energy": 812.4,
        "sensor.em_hot_water_grid_energy": 300.0,
        "sensor.em_hot_water_solar_energy": 512.4,
        "sensor.thermann_shadow_bottom_temperature": 41.0,
        "sensor.home_status_age": 600,
    }
    trigger = changed("on", "start")
    snapshot = {
        key: render(template, at_start, began, this=None, trigger=trigger)
        for key, template in start_sensor["attributes"].items()
    }
    started = render(start_sensor["state"], at_start, began, this=None, trigger=trigger)
    assert started == began.isoformat()
    assert snapshot == {
        "energy_kwh": 812.4,
        "grid_kwh": 300.0,
        "solar_kwh": 512.4,
        "temperature_c": 41.0,
        "status_age_s": 600.0,
    }

    at_end = {
        "sensor.em_hot_water_energy": 817.2,
        "sensor.em_hot_water_grid_energy": 301.2,
        "sensor.em_hot_water_solar_energy": 516.0,
        "sensor.thermann_shadow_bottom_temperature": 58.5,
        "sensor.home_status_age": 120,
        "sensor.em_tariff_period": "off_peak",
        "sensor.em_hot_water_cycle_start": {"state": started, "attributes": snapshot},
    }
    trigger = changed("off", "end")
    energy = render(last_sensor["state"], at_end, ended, this=None, trigger=trigger)
    attributes = {
        key: render(template, at_end, ended, this=None, trigger=trigger)
        for key, template in last_sensor["attributes"].items()
    }
    reference = calc.cycle_summary(
        {
            "time": began,
            "energy_kwh": 812.4,
            "grid_kwh": 300.0,
            "solar_kwh": 512.4,
            "temperature_c": 41.0,
        },
        {
            "time": ended,
            "energy_kwh": 817.2,
            "grid_kwh": 301.2,
            "solar_kwh": 516.0,
            "temperature_c": 58.5,
        },
    )
    assert energy == reference["energy_kwh"] == 4.8
    assert attributes["duration_minutes"] == reference["duration_minutes"] == 96.0
    assert attributes["grid_kwh"] == reference["grid_kwh"] == 1.2
    assert attributes["solar_kwh"] == reference["solar_kwh"] == 3.6
    assert attributes["temperature_rise_c"] == reference["temperature_rise_c"] == 17.5
    assert attributes["started"] == began.isoformat()
    assert attributes["status_age_start_s"] == 600.0
    assert attributes["status_age_end_s"] == 120.0
    assert reference["solar_fraction"] == 0.75
    assert reference["average_power_w"] == 3000

    # The next start keeps the completed cycle untouched.
    kept = previous(energy, **attributes)
    trigger = changed("on", "start")
    assert render(last_sensor["state"], at_end, ended, this=kept, trigger=trigger) == 4.8
    for key, template in last_sensor["attributes"].items():
        assert render(template, at_end, ended, this=kept, trigger=trigger) == attributes[key]


def test_an_off_without_a_new_start_never_invents_a_cycle(package):
    """Meter drop-out: off -> unavailable -> on misses the start. The following
    on -> off must not be paired with the previous run's start."""
    last_sensor = entity(package, "EM hot water last cycle")
    old_start = "2026-11-16T01:00:00+00:00"
    recorded = previous(
        4.8, started=old_start, ended="2026-11-16T02:36:00+00:00", duration_minutes=96.0
    )
    states = {
        "sensor.em_hot_water_energy": 830.0,
        "sensor.em_hot_water_grid_energy": 310.0,
        "sensor.em_hot_water_solar_energy": 520.0,
        "sensor.em_hot_water_cycle_start": {
            "state": old_start,
            "attributes": {"energy_kwh": 812.4, "grid_kwh": 300.0, "solar_kwh": 512.4},
        },
    }
    later = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
    trigger = changed("off", "end")
    assert render(last_sensor["state"], states, later, this=recorded, trigger=trigger) == 4.8
    for key in ("started", "ended", "duration_minutes"):
        template = last_sensor["attributes"][key]
        value = render(template, states, later, this=recorded, trigger=trigger)
        assert value == recorded.attributes[key]
    # A properly started run after that is recorded as usual.
    states["sensor.em_hot_water_cycle_start"]["state"] = "2026-11-16T08:00:00+00:00"
    states["sensor.em_hot_water_cycle_start"]["attributes"]["energy_kwh"] = 827.0
    assert render(last_sensor["state"], states, later, this=recorded, trigger=trigger) == 3.0
    minutes = last_sensor["attributes"]["duration_minutes"]
    assert render(minutes, states, later, this=recorded, trigger=trigger) == 60.0


def test_circuit_readings_accept_the_units_the_controller_accepts():
    config = with_meters()
    config["circuits"][0]["energy"] = "sensor.ct_hot_water_energy"
    built = build_package(config)
    power, energy = entity(built, "EM hot water power"), entity(built, "EM hot water energy")

    def reading(value, unit):
        return {"state": value, "attributes": {"unit_of_measurement": unit}}

    assert render(power["state"], {"sensor.ct_hot_water_power": reading(2987.3, "W")}) == 2987.3
    assert render(power["state"], {"sensor.ct_hot_water_power": reading(2.9873, "kW")}) == 2987.3
    assert render(power["state"], {"sensor.ct_hot_water_power": 2987.3}) == 2987.3
    assert render(energy["state"], {"sensor.ct_hot_water_energy": reading(812.4, "kWh")}) == 812.4
    assert render(energy["state"], {"sensor.ct_hot_water_energy": reading(812400, "Wh")}) == 812.4
    assert render(power["availability"], {"sensor.ct_hot_water_power": "unavailable"}) is False


def test_a_cycle_with_missing_readings_reports_none_not_a_guess(package):
    last_sensor = entity(package, "EM hot water last cycle")
    states = {
        "sensor.em_hot_water_energy": "unavailable",
        "sensor.em_hot_water_cycle_start": "unknown",
    }
    trigger = changed("off", "end")
    assert render(last_sensor["state"], states, this=None, trigger=trigger) is None
    for key in ("duration_minutes", "grid_kwh", "temperature_rise_c", "started"):
        value = render(last_sensor["attributes"][key], states, this=None, trigger=trigger)
        assert value is None
    summary = calc.cycle_summary(
        {"time": datetime(2026, 1, 1, tzinfo=timezone.utc), "energy_kwh": None},
        {"time": datetime(2026, 1, 1, 1, tzinfo=timezone.utc), "energy_kwh": 3.0},
    )
    assert summary["energy_kwh"] is None and summary["average_power_w"] is None


def test_rollup_counts_daylight_saving_days_once():
    from datetime import date

    daily = {date(2026, 10, 3) + timedelta(days=offset): 10.0 for offset in range(4)}
    assert calc.rollup(daily, "day")["2026-10-04"] == 10.0  # the 23-hour day
    assert calc.rollup(daily, "week") == {"2026-W40": 20.0, "2026-W41": 20.0}
    assert calc.rollup(daily, "month") == {"2026-10": 40.0}
    assert calc.rollup({date(2026, 12, 31): 1.0, date(2027, 1, 1): 2.0}, "year") == {
        "2026": 1.0,
        "2027": 2.0,
    }
    with pytest.raises(ValueError):
        calc.rollup(daily, "decade")


def test_day_cost_separates_import_cost_from_feed_in():
    day = calc.DayCost(
        4.0, 10.0, 12.0, {"peak": 0.36, "off_peak": 0.17, "feed_in": 0.09, "supply": 1.2}
    )
    assert day.import_cost == pytest.approx(3.14)
    assert day.export_earnings == pytest.approx(1.08)
    assert day.net == pytest.approx(3.14 - 1.08 + 1.2)
