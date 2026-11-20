"""Economic comparisons are reproducible, equal-service, and preserve defaults."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location(
    "controller_replay", ROOT / "tools/controller_replay.py"
)
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


def test_faster_withdrawal_can_save_or_cost_dollars_for_equal_service():
    def dark(i):
        return 3.5 if i < 13 else 0

    def cloud(i):
        return 0 if 14 <= i < 18 else 3.5

    slow_dark = replay.dispatch_case("dark", dark, 5)
    fast_dark = replay.dispatch_case("dark", dark, 2)
    slow_cloud = replay.dispatch_case("cloud", cloud, 5)
    fast_cloud = replay.dispatch_case("cloud", cloud, 2)
    assert slow_dark["net_heat_cost_aud"] - fast_dark["net_heat_cost_aud"] == pytest.approx(
        0.02875, abs=0.001
    )
    assert fast_cloud["net_heat_cost_aud"] - slow_cloud["net_heat_cost_aud"] == pytest.approx(
        -0.1 * 0.361878 + 0.7 * 0.1702 - 0.6 * 0.09276, abs=0.000002
    )
    for row in (slow_dark, fast_dark, slow_cloud, fast_cloud):
        assert row["equal_service_achieved"] and row["useful_heat_kwh"] == pytest.approx(1.5)
        assert row["peak_import_kwh"] + row["off_peak_import_kwh"] + row[
            "heater_solar_kwh"
        ] == pytest.approx(1.5)


def test_request_ledger_accounts_for_all_calls_and_detection_tradeoff():
    rows = [replay.polling_day(x) for x in ("30", "60", "adaptive")]
    assert rows[0]["total_http"] > rows[1]["total_http"] > rows[2]["total_http"]
    assert (
        rows[0]["persistent_owner_event_detection_minutes"]
        < rows[2]["persistent_owner_event_detection_minutes"]
    )
    for row in rows:
        assert row["total_http"] == sum(row["http"].values())
        assert row["http"]["command_post"] == row["http"]["confirmation_status"] == 4
        assert row["maximum_status_gap_minutes"] <= (
            int(row["strategy"]) if row["strategy"].isdigit() else 90
        )


def test_checked_in_replay_results_match_the_current_code():
    saved = json.loads((ROOT / "docs/history/smart-controller/SIMULATION_RESULTS.json").read_text())
    assert saved == replay.report()


def test_forecast_error_does_not_keep_optional_peak_heating_on_import():
    result = replay.dispatch_case("forecast_says_sun_but_dark", lambda i: 3.5 if i < 13 else 0)
    assert result["commands"][-1]["reason"] == "peak_solar_withdrawn"
    assert result["forecast_error_mae_kw"] > 0
