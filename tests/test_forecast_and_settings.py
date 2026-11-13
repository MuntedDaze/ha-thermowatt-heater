"""Counterfactual forecasts, economics, cycle hysteresis and saved preferences."""

from datetime import timedelta
import importlib
import json
from types import SimpleNamespace

import pytest

from test_shadow_model import c, m, local, readings, runtime  # noqa: F401

forecast = importlib.import_module(f"{m.__package__}.forecast")
catalog = importlib.import_module(f"{m.__package__}.settings")


def series(now, kind="pv", value=4, **attrs):
    key = "p_pv_forecast" if kind == "pv" else "p_load_forecast"
    return SimpleNamespace(
        state="0",
        attributes={
            "unit_of_measurement": "kW",
            "forecast_generated_at": now.isoformat(),
            "forecasts": [
                {"date": (now + timedelta(hours=i)).isoformat(), key: value} for i in range(7)
            ],
            **attrs,
        },
    )


def test_forecasts_use_household_load_uncertainty_and_downward_actual_error():
    now = local(hour=11)
    settings, _ = c.parse_options({"forecast_enabled": True})
    result = forecast.build_forecast(
        now, now - timedelta(minutes=1), settings, series(now), series(now, "load", 1), 2
    )
    assert result.slots[0].export_kw == pytest.approx(max(0, 4 * 0.5 * 0.75 - 1 * 1.25 - 0.3))
    assert result.pv_error_kw == -2 and result.correction == 0.5
    bright = forecast.build_forecast(
        now, now - timedelta(minutes=1), settings, series(now), series(now, "load", 1), 6
    )
    # 0.4.0: correction is two-way but bounded (x1.3); 6 kW measured is clipped
    # output (>= 4.85 kW of the 5 kW AC limit), a LOWER bound on potential.
    assert bright.correction == 1.3 and bright.clipped_now
    assert bright.slots[0].export_kw == pytest.approx(min(5.0, 4 * 1.3) * 0.75 - 1.25 - 0.3)
    assert bright.slots[-1].end == now + timedelta(hours=6)


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "old",
        "preboot",
        "future",
        "unit",
        "nan",
        "negative",
        "bool",
        "oversized",
        "naive",
        "unsorted",
        "overlap",
        "generation_missing",
        "unavailable",
        "restored",
        "no_load",
    ],
)
def test_bad_forecasts_fall_back_without_blocking_temperature_plan(case):
    now = local(hour=11)
    settings, tariffs = c.parse_options({"forecast_enabled": True})
    pv, load = series(now), series(now, "load", 1)
    if case == "missing":
        pv = None
    elif case == "old":
        pv.attributes["forecast_generated_at"] = (now - timedelta(hours=3)).isoformat()
    elif case == "preboot":
        pv.attributes["forecast_generated_at"] = (now - timedelta(minutes=2)).isoformat()
    elif case == "future":
        pv.attributes["forecast_generated_at"] = (now + timedelta(minutes=1)).isoformat()
    elif case == "unit":
        pv.attributes["unit_of_measurement"] = "kWh"
    elif case in {"nan", "negative", "bool"}:
        pv.attributes["forecasts"][0]["p_pv_forecast"] = {
            "nan": "nan",
            "negative": -1,
            "bool": True,
        }[case]
    elif case == "oversized":
        pv.attributes["forecasts"] *= 100
    elif case == "naive":
        pv.attributes["forecasts"][0]["date"] = "2026-11-10T11:00:00"
    elif case == "unsorted":
        pv.attributes["forecasts"].reverse()
    elif case == "overlap":
        pv.attributes["forecasts"][1] = pv.attributes["forecasts"][0]
    elif case == "generation_missing":
        del pv.attributes["forecast_generated_at"]
    elif case == "unavailable":
        pv.state = "unavailable"
    elif case == "restored":
        pv.attributes["restored"] = True
    elif case == "no_load":
        load = None
    result = forecast.build_forecast(now, now - timedelta(minutes=1), settings, pv, load)
    assert not result.slots and result.warnings  # the policy then sees no forecast


def test_forecast_solar_watts_adapter_and_grid_load_spike():
    now = local(hour=11)
    settings, _ = c.parse_options(
        {"forecast_enabled": True, "forecast_uncertainty": 0, "forecast_house_margin_kw": 0}
    )
    pv = series(now, watts={(now + timedelta(hours=i)).isoformat(): 4000 for i in range(7)})
    result = forecast.build_forecast(
        now, now - timedelta(minutes=1), settings, pv, series(now, "load", 1)
    )
    assert result.slots[0].export_kw == 3
    result = forecast.build_forecast(
        now, now - timedelta(minutes=1), settings, pv, series(now, "load", 5)
    )
    assert result.slots[0].export_kw == 0


@pytest.mark.parametrize(
    "key,value",
    [
        ("solar_loss_minutes", -1),
        ("minimum_cycle_minutes", 181),
        ("minimum_gap_minutes", float("nan")),
        ("switching_benefit_aud", -1),
        ("forecast_uncertainty", 1),
        ("forecast_enabled", "true"),
        ("morning_time", "12:00"),
        ("evening_time", "10:00"),
        ("peak_morning_end", "16:30"),
        ("forecast_max_age_minutes", 0),
    ],
)
def test_new_preferences_reject_invalid_values_atomically(key, value):
    with pytest.raises((ValueError, TypeError)):
        c.parse_options({key: value})


@pytest.mark.parametrize("profile", ["aurora_93", "custom"])
@pytest.mark.parametrize(
    "periods",
    [
        "[]",
        "not json",
        json.dumps([{"days": [0], "start": "00:00", "end": "00:00", "kind": "off_peak"}]),
        json.dumps([{"days": list(range(7)), "start": "00:00", "end": "00:00", "kind": "free"}]),
    ],
)
def test_stored_custom_periods_are_validated_even_in_aurora_mode(profile, periods):
    """Regression for the actual HA options-flow CI failure on 643ab8a.

    The Aurora profile previously ignored the persisted custom table, so an
    invalid table was saved and would only fail once the profile select changed.
    """
    with pytest.raises((ValueError, TypeError)):
        c.parse_options({"tariff_profile": profile, "tariff_periods": periods})


def test_legacy_options_upgrade_and_recommended_restore_preserve_authority():
    old = {
        "target_c": 65,
        "meter_verified": False,
        "import_positive": True,
        "sources": {"heater": "water_heater.owner"},
        "tariff_periods": json.dumps(
            [{"days": list(range(7)), "start": "00:00", "end": "00:00", "kind": "off_peak"}]
        ),
    }
    values = c.saved_options(old)
    assert values["tariff_profile"] == "custom"
    settings, tariffs = c.parse_options(values)
    assert settings.target_c == 65 and not settings.meter_verified and len(tariffs) == 1
    restored = catalog.recommended_options(values)
    assert restored["target_c"] == 70 and restored["switching_benefit_aud"] == 0.10
    assert (
        restored["sources"] == old["sources"]
        and not restored["meter_verified"]
        and restored["import_positive"]
    )
    assert set(catalog.CATALOG) == set(c.DEFAULT_OPTIONS)


def test_runtime_forecast_mapping_and_local_cycle_settings_reset(runtime):  # noqa: F811
    instance, report, clock = runtime
    instance.update(clock[0])
    original_sources = dict(instance.sources)
    instance.apply_options({"target_c": 65, "morning_time": "06:30"}, instance.sources)
    assert instance.settings.target_c == 65 and instance.settings.morning.hour == 6
    assert dict(instance.sources) == original_sources and not hasattr(instance.hass, "services")
    assert instance.details["additional_cloud_requests"] == 0
    json.dumps(instance.details, allow_nan=False)
