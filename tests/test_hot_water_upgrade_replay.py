"""Reproducible four-strategy comparison with production mocked command path."""

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
        replay = importlib.import_module("hot_water_upgrade_replay")
    finally:
        sys.path.pop(0)
    return replay.results()


def test_current_report_reproduces_all_four_strategies_and_conserves_heat(report):
    assert report == json.loads((ROOT / "docs/completion/SIMULATION_RESULTS.json").read_text())
    assert len(report["runs"]) == 24 and report["synthetic"]
    physics = 315 * 4.186 / 3600
    for row in report["runs"]:
        assert row["http_total"] == sum(row["http"].values())
        assert row["command_posts"] == row["http"]["command"]
        assert row["heat_kwh"] == pytest.approx(
            row["solar_kwh"] + row["peak_import_kwh"] + row["off_peak_import_kwh"], abs=0.000003
        )
        # The native thermostat model loses0.2C each simulated hour.
        assert row["heat_kwh"] == pytest.approx(
            (row["end_temperature_c"] - 46 + 4.8) * physics + row["draw_kwh"], abs=0.001
        )
        if row["strategy"] in {"required_only", "off_peak_solar"}:
            assert row["peak_import_kwh"] == 0
        if row["strategy"] == "required_only":
            assert row["optional_start_intents"] == 0
        assert row["confirmation_failures"] == 0


def test_peak_cloud_and_unrelated_appliance_cost_exposure_is_visible(report):
    rows = {(r["scenario"], r["strategy"]): r for r in report["runs"]}
    for scenario in ("sustained_cloud", "appliance"):
        ct_free = rows[scenario, "ct_free_all_solar"]
        assert ct_free["peak_import_kwh"] > 0
        assert ct_free["grid_cost_aud"] > 0
    for row in report["runs"]:
        assert (
            row["equal_terminal_heat_cost_aud"]
            >= row["grid_cost_aud"] + row["foregone_export_aud"] - 0.000002
        )
