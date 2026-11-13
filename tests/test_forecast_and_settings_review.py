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


def test_forecast_solar_overnight_gap_is_zero_solar_not_an_invalid_series():
    now = local(hour=11)
    settings, _ = c.parse_options(
        {"forecast_enabled": True, "forecast_uncertainty": 0, "forecast_house_margin_kw": 0}
    )
    result = forecast.build_forecast(
        now, now - timedelta(minutes=1), settings, forecast_solar_state(now), series(now, "load", 1)
    )
    assert result.source == "published_pv_and_house_load", result.warnings
    assert result.slots[0].export_kw == pytest.approx(3.5)
    overnight = [
        slot
        for slot in result.slots
        if slot.start.astimezone(m.HOBART).hour >= 20 or slot.start.astimezone(m.HOBART).hour < 6
    ]
    assert not overnight  # a gap never becomes free (or held) solar


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
    load = series(now, "load", 0)
    result = forecast.build_forecast(now, now - timedelta(minutes=1), settings, pv, load, 1)
    assert result.correction == 0.25 and result.pv_error_kw == -3
    by_start = {slot.start: slot.export_kw for slot in result.slots}
    assert by_start[now] == pytest.approx(1)
    assert by_start[now + timedelta(hours=1.5)] == pytest.approx(4 * (1 - 0.5 * 0.75))
    assert by_start[now + timedelta(hours=3)] == pytest.approx(4)  # faded out
    assert max(by_start.values()) <= 4
    # Upward correction exists but is bounded and never exceeds the AC limit.
    up = forecast.build_forecast(
        now, now - timedelta(minutes=1), settings, series(now, value=2), load, 3
    )
    assert up.correction == 1.3 and not up.clipped_now
    assert max(item[2] for item in up.pv_series) <= settings.pv_ac_limit_kw


def test_flat_statistics_household_baseline_and_its_freshness():
    now = local(hour=11)
    settings, _ = c.parse_options(
        {"forecast_enabled": True, "forecast_uncertainty": 0.25, "forecast_house_margin_kw": 0.3}
    )
    baseline = SimpleNamespace(
        state="800", attributes={"unit_of_measurement": "W"}, last_reported=now
    )
    result = forecast.build_forecast(
        now, now - timedelta(minutes=1), settings, series(now), baseline
    )
    assert result.load_basis == "flat_measured_household_baseline"
    assert result.slots[0].export_kw == pytest.approx(4 * 0.75 - 0.8 * 1.25 - 0.3)
    assert "household_load_is_flat_baseline_not_daily_profile" in result.warnings
    baseline.last_reported = now - timedelta(hours=3)
    stale = forecast.build_forecast(now, now - timedelta(hours=4), settings, series(now), baseline)
    assert not stale.slots and "forecast_stale_or_pre_restart" in stale.warnings


# --- Restore, undo and truthful defaults -------------------------------------------


def test_restore_preserves_tariff_contract_and_undo_reverts_only_preferences():
    current = c.saved_options(
        {
            "target_c": 65,
            "margin_minutes": 45,
            "peak_rate": 0.4,
            "feed_in_rate": 0.05,
            "peak_evening_start": "17:00",
            "paused": True,
        }
    )
    restored = catalog.recommended_options(current)
    assert restored["target_c"] == 70 and restored["margin_minutes"] == 30
    assert restored["peak_rate"] == 0.4 and restored["feed_in_rate"] == 0.05
    assert restored["peak_evening_start"] == "17:00" and restored["paused"] is True
    assert restored[catalog.BACKUP_KEY] == {"target_c": 65, "margin_minutes": 45}
    c.parse_options(restored)  # stored snapshot does not break validation
    edited = catalog.apply_changes(restored, {"margin_minutes": 20})
    assert edited[catalog.BACKUP_KEY] == {"target_c": 65}  # newest owner edit wins
    undone = catalog.undo_restore(edited)
    assert undone["target_c"] == 65 and undone["margin_minutes"] == 20
    assert catalog.BACKUP_KEY not in undone
    with pytest.raises(ValueError):
        catalog.undo_restore(undone)
    again = catalog.recommended_options(catalog.recommended_options(current))
    assert catalog.BACKUP_KEY not in again  # nothing new changed: no stale undo


def test_describe_reports_current_recommended_and_original():
    info = catalog.describe("switching_benefit_aud", 0.2)
    assert info["current_value"] == 0.2 and info["recommended_default"] == 0.10
    assert info["original_default"] == 0.10 and info["recommended_equals_original"]
    assert info["changed_from_recommended"] and info["restore_recommended"] == "restores"
    assert catalog.describe("peak_rate", 0.361878)["restore_recommended"] == "preserves"
    # Original defaults are pinned: a future recommendation change must not
    # silently rewrite what shipped. Update DEFAULT_OPTIONS only, never this.
    pinned = {
        "morning_threshold_c": 40.0,
        "morning_time": "07:00",
        "target_c": 70.0,
        "margin_minutes": 30.0,
        "solar_hold_minutes": 10.0,
        "solar_loss_minutes": 20.0,
        "minimum_cycle_minutes": 30.0,
        "minimum_gap_minutes": 30.0,
        "export_headroom_kw": 0.3,
        "switching_benefit_aud": 0.10,
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
