"""Reproducible economic evidence, conservation and service accounting."""

import importlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def report():
    sys.path.insert(0, str(ROOT / "tools"))
    try:
        replay = importlib.import_module("dual_storage_replay")
    finally:
        sys.path.pop(0)
    return replay.results()


def row(report, case, strategy):
    return next(r for r in report["rows"] if r["scenario"] == case and r["strategy"] == strategy)


def test_saved_comparison_is_current_and_all_energy_is_accounted_for(report):
    saved = json.loads((ROOT / "docs/history/dual-storage/SIMULATION_RESULTS.json").read_text())
    assert report == saved
    assert report["cases"] >= 10 and len(report["rows"]) == report["cases"] * 3
    kwh_per_c = 315 * 4.186 / 3600
    for r in report["rows"]:
        input_energy = r["peak_import_kwh"] + r["off_peak_import_kwh"] + r["heater_solar_kwh"]
        stored_change = (r["end_temperature_c"] - r["initial_c"]) * kwh_per_c
        assert input_energy == pytest.approx(
            stored_change + r["standing_loss_kwh"] + r["useful_draw_kwh"], abs=0.000003
        )
        assert r["peak_import_kwh"] == 0  # synthetic OFF, not proof about real native cycles
        assert r["unserved_draw_kwh"] == 0
        assert r["modelled_cloud_request_count"] == sum(r["modelled_cloud_requests"].values())
        assert r["modelled_cloud_requests"]["command_post"] == r["command_count"]
        assert r["end_stored_above_15_kwh"] + r["terminal_replenishment_kwh"] == pytest.approx(
            r["common_terminal_stored_kwh"], abs=0.000002
        )
        assert r["equal_service_terminal_cost_aud"] >= r["net_energy_cost_aud"]


def test_sun_uses_direct_boost_and_later_forecast_update_allows_topup(report):
    sunny = row(report, "strong_sun_direct_70", "dual_62_optional_70")
    assert sunny["commands"][1]["target_c"] == 70
    assert sunny["commands"][1]["reason"] == "weekday_direct_solar_boost"
    topup = row(report, "unexpected_solar_after_normal", "dual_62_optional_70")
    assert [c["target_c"] for c in topup["commands"] if c["target_c"] in (62, 70)] == [62, 70]


def test_cloudy_ct_free_disabled_and_weekend_remain_supported(report):
    for case in ("cloudy_off_peak", "ct_free_required_storage", "forecast_sun_never_arrives"):
        r = row(report, case, "dual_62_optional_70")
        assert all(c["target_c"] != 70 for c in r["commands"])
        assert any(c["target_c"] == 62 for c in r["commands"])
    for r in report["rows"]:
        if r["strategy"] == "required_62":
            assert all(c["target_c"] != 70 for c in r["commands"])
        if r["scenario"].startswith("weekend"):
            # 0.17.0: the weekend window ends at 18:00 AEDT and returns to 45.
            assert r["commands"][-1]["target_c"] == 45
            assert r["commands"][-1]["reason"] == "weekend_day_ended"
    cloudy = row(report, "weekend_cloud", "dual_62_optional_70")
    assert [c["target_c"] for c in cloudy["commands"]] == [62, 45]  # deadline fallback
    late = row(report, "late_cold_start_before_peak", "dual_62_optional_70")
    assert late["required_probe_target_reached_by_peak"] is False
    assert late["storage_shortfall_at_peak_kwh"] > 5


def test_lower_raw_cost_cannot_hide_lower_terminal_energy(report):
    prior = row(report, "cloudy_off_peak", "previous_required_70")
    normal = row(report, "cloudy_off_peak", "required_62")
    assert prior["net_energy_cost_aud"] > normal["net_energy_cost_aud"]
    assert prior["end_stored_above_15_kwh"] > normal["end_stored_above_15_kwh"]
    assert normal["terminal_replenishment_kwh"] > 2
    assert normal["equal_service_terminal_cost_aud"] - normal["net_energy_cost_aud"] > 0.4
