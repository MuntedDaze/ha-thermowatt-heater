"""Claude review of Phase 2B: decisions, forecast adapters, restore/undo, averaging."""

from datetime import timedelta
import json
from types import SimpleNamespace

import pytest

from test_shadow_model import c, m, local, readings, runtime  # noqa: F401
from test_forecast_and_settings import catalog, forecast, series


# --- Decisions: every branch is reachable and honest --------------------------------


# --- Forecast adapters -------------------------------------------------------------


def forecast_solar_state(now, **attrs):
    """Shape of an owner trigger-template buffer of forecast_solar.get_forecast."""
    today = now.astimezone(m.HOBART).replace(minute=0, second=0, microsecond=0)
    watts = {}
    for day in (0, 1):
        for hour in range(6, 20):
            at = (today.replace(hour=hour) + timedelta(days=day)).isoformat()
            watts[at] = 0 if hour in (6, 19) else 4500
    return SimpleNamespace(
        state=str(len(watts)),
        attributes={
            "unit_of_measurement": "W",
            "watts": watts,
            "forecast_generated_at": now.isoformat(),
            **attrs,
        },
    )


def test_retired_forecast_solar_shape_assumes_no_solar():
    """0.18.1: only the EMHASS forecasts series is a forecast; anything else
    means no future solar is assumed (required heating continues unchanged)."""
    now = local(hour=11)
    settings, _ = c.parse_options({"forecast_enabled": True})
    result = forecast.build_forecast(
        now, now - timedelta(minutes=1), settings, forecast_solar_state(now), series(now, "load", 1)
    )
    assert result.source == "unavailable" and not result.slots


def test_emhass_string_values_and_custom_entity_keys_are_read():
    now = local(hour=11)
    settings, _ = c.parse_options(
        {"forecast_enabled": True, "forecast_uncertainty": 0, "forecast_house_margin_kw": 0}
    )

    def emhass(key, value):
        rows = [
            {"date": (now + timedelta(minutes=30 * i)).isoformat(), key: str(value)}
            for i in range(8)
        ]
        return SimpleNamespace(
            state=str(value),
            attributes={
                "unit_of_measurement": "W",
                "forecasts": rows,
                "forecast_generated_at": now.isoformat(),
            },
        )

    result = forecast.build_forecast(
        now,
        now - timedelta(minutes=1),
        settings,
        emhass("mpc_pv_forecast", 4000.0),
        emhass("p_load_forecast", 750.5),
    )
    assert result.slots[0].export_kw == pytest.approx(3.2495)
    ambiguous = emhass("mpc_pv_forecast", 4000)
    ambiguous.attributes["forecasts"][0]["extra"] = 1
    bad = forecast.build_forecast(
        now, now - timedelta(minutes=1), settings, ambiguous, emhass("p_load_forecast", 1)
    )
    assert not bad.slots and "forecast_series_invalid" in bad.warnings


def test_measured_pv_correction_fades_and_is_bounded():
    now = local(hour=11)
    settings, _ = c.parse_options(
        {"forecast_enabled": True, "forecast_uncertainty": 0, "forecast_house_margin_kw": 0}
    )
    pv = series(now, value=4)
    load = series(now, "load", 0.1)
    result = forecast.build_forecast(now, now - timedelta(minutes=1), settings, pv, load, 1)
    assert result.correction == 0.25 and result.pv_error_kw == -3
    by_start = {slot.start: slot.export_kw for slot in result.slots}
    assert by_start[now] == pytest.approx(0.9)
    assert by_start[now + timedelta(hours=1.5)] == pytest.approx(4 * (1 - 0.5 * 0.75) - 0.1)
    assert by_start[now + timedelta(hours=3)] == pytest.approx(3.9)  # faded out
    assert max(by_start.values()) <= 4
    # Upward correction exists but is bounded and never exceeds the AC limit.
    up = forecast.build_forecast(
        now, now - timedelta(minutes=1), settings, series(now, value=2), load, 3
    )
    assert up.correction == 1.3 and not up.clipped_now
    assert max(item[2] for item in up.pv_series) <= settings.pv_ac_limit_kw


def test_non_emhass_household_load_uses_only_the_conservative_floor():
    """0.18.1: the flat Statistics-helper baseline is retired; there is no second
    household-load model, only the documented floor (or the current house load)."""
    now = local(hour=11)
    settings, _ = c.parse_options(
        {"forecast_enabled": True, "forecast_uncertainty": 0.25, "forecast_house_margin_kw": 0.3}
    )
    baseline = SimpleNamespace(
        state="800",
        attributes={
            "unit_of_measurement": "W",
            "age_coverage_ratio": 0.9,
            "source_value_valid": True,
        },
        last_reported=now,
    )
    result = forecast.build_forecast(
        now, now - timedelta(minutes=1), settings, series(now), baseline
    )
    assert result.load_basis == "conservative_assumed_household_floor"
    assert result.load_floor_kw == forecast.FALLBACK_LOAD_KW == 1.0
    assert result.slots[0].export_kw == pytest.approx(4 * 0.75 - 1.0 * 1.25 - 0.3)


# --- Restore, undo and truthful defaults -------------------------------------------


def test_restore_preserves_tariff_contract_and_undo_reverts_only_preferences():
    current = c.saved_options(
        {
            "forecast_uncertainty": 0.4,
            "pv_ac_limit_kw": 6.0,
            "peak_rate": 0.4,
            "feed_in_rate": 0.05,
            "peak_evening_start": "17:00",
            "retired_options": {"paused": True},
        }
    )
    restored = catalog.recommended_options(current)
    assert restored["forecast_uncertainty"] == 0.25 and restored["pv_ac_limit_kw"] == 5.0
    assert restored["peak_rate"] == 0.4 and restored["feed_in_rate"] == 0.05
    assert restored["peak_evening_start"] == "17:00"
    assert restored["retired_options"] == {"paused": True}  # never touched by Restore
    assert restored[catalog.BACKUP_KEY] == {"forecast_uncertainty": 0.4, "pv_ac_limit_kw": 6.0}
    c.parse_options(restored)  # stored snapshot does not break validation
    edited = catalog.apply_changes(restored, {"pv_ac_limit_kw": 7.0})
    assert edited[catalog.BACKUP_KEY] == {"forecast_uncertainty": 0.4}  # newest edit wins
    undone = catalog.undo_restore(edited)
    assert undone["forecast_uncertainty"] == 0.4 and undone["pv_ac_limit_kw"] == 7.0
    assert catalog.BACKUP_KEY not in undone
    with pytest.raises(ValueError):
        catalog.undo_restore(undone)
    again = catalog.recommended_options(catalog.recommended_options(current))
    assert catalog.BACKUP_KEY not in again  # nothing new changed: no stale undo


def test_describe_reports_current_recommended_and_original():
    info = catalog.describe("forecast_uncertainty", 0.2)
    assert info["current_value"] == 0.2 and info["recommended_default"] == 0.25
    assert info["original_default"] == 0.25 and info["recommended_equals_original"]
    assert info["changed_from_recommended"] and info["restore_recommended"] == "restores"
    assert catalog.describe("peak_rate", 0.361878)["restore_recommended"] == "preserves"
    # Original defaults are pinned: a future recommendation change must not
    # silently rewrite what shipped. Update DEFAULT_OPTIONS only, never this.
    pinned = {
        "peak_rate": 0.361878,
        "off_peak_rate": 0.170200,
        "feed_in_rate": 0.092760,
        "tariff_clock": "standard",
    }
    assert {key: catalog.ORIGINAL_DEFAULTS[key] for key in pinned} == pinned


# --- Runtime: averaging, native load warning, decision wiring -----------------------


def test_runtime_pv_average_damps_a_single_cloudy_sample(runtime):  # noqa: F811
    instance, report, clock = runtime
    instance.apply_options({"forecast_enabled": True}, instance.sources)
    instance.sources = {
        **instance.sources,
        "forecast_pv": "sensor.pv_f",
        "forecast_load": "sensor.ld",
    }
    states = instance.hass.states
    original_get = states.get
    start = clock[0]

    def get(entity):
        if entity == "sensor.pv_f":
            return series(start, value=4)
        if entity == "sensor.ld":
            return series(start, "load", 0.5)
        return original_get(entity)

    instance.hass.states = SimpleNamespace(get=get)
    instance.boot = start - timedelta(minutes=1)
    for minute, watts in enumerate([4000, 4000, 4000, 400], start=1):
        clock[0] = start + timedelta(minutes=minute)
        for key, value in {"grid": 3000, "pv_ac": watts, "house": 500}.items():
            report(key, value, {"unit_of_measurement": "W"})
        report("last_poll", clock[0].isoformat())
        instance.update(clock[0])
    # Rolling mean of fresh distinct reports (2.322 from setup, then 4, 4, 4, 0.4):
    assert instance.forecast.measured_pv_average_kw == pytest.approx(14.722 / 5, abs=1e-3)
    assert instance.forecast.correction == pytest.approx(14.722 / 5 / 4, abs=1e-3)
    assert instance.values.get("decision") is None  # no executor: the policy is not run here
    json.dumps(instance.details, allow_nan=False, default=str)
