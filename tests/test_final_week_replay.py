"""Eight full weeks through the real controller/worker; all external I/O denied."""

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
        replay = importlib.import_module("final_week_replay")
    finally:
        sys.path.pop(0)
    return replay.results()


def test_week_replay_is_current_and_service_energy_requests_are_accounted_for(report):
    saved = json.loads((ROOT / "docs/evidence/WEEK_RESULTS.json").read_text(encoding="utf-8"))
    assert report == saved
    assert len(report["runs"]) == 4
    physics = 315 * 4.186 / 3600
    for row in report["runs"]:
        energy = row["energy_kwh"]
        assert len(row["days"]) == 7
        assert energy["served_draw"] == 45 and energy["unserved_draw"] == 0
        assert energy["peak"] + energy["off_peak"] + energy["solar"] == pytest.approx(
            (row["end_temperature_c"] - 45) * physics + energy["served_draw"] + energy["loss"],
            abs=0.000003,
        )
        assert energy["peak"] == pytest.approx(
            energy["peak_owner"] + energy["peak_unverified_lockout"], abs=0.000002
        )
        assert row["http_total"] == sum(row["http_categories"].values())
        assert row["command_posts"] == row["http_categories"]["command"]
        assert row["command_intents"] >= row["command_posts"]
        assert row["end_stored_above_15_kwh"] + row["terminal_replenishment_kwh"] == pytest.approx(
            row["common_terminal_stored_kwh"], abs=0.000002
        )
        assert row["equal_terminal_cost_aud"] >= row["net_heater_cost_aud"]


def test_less_frequent_fixed_reads_trade_detection_for_requests(report):
    for ct in (False, True):
        group = {r["strategy"]: r for r in report["runs"] if r["ct"] == ct}
        fixed = group["fixed_30"]
        assert (
            group["fixed_60"]["unknown_temperature_minutes"] > fixed["unknown_temperature_minutes"]
        )
        assert (
            group["fixed_60"]["persistent_owner_detection_minutes"]
            > fixed["persistent_owner_detection_minutes"]
        )


def test_failures_restart_and_missing_ct_do_not_manufacture_success(report):
    for row in report["runs"]:
        assert any("restart_no_intent_replay" in e["event"] for e in row["events"])
        assert row["persistent_owner_detection_minutes"] is not None
        assert row["transient_app_change_observed"] is False  # five minutes between sparse reads
        assert (
            row["energy_kwh"]["peak_unverified_lockout"] > 0
        )  # outage is not proved electrical OFF
        assert row["days"]["2026-11-20"]["at_peak_storage_shortfall_kwh"] > 0
        if not row["ct"]:
            assert row["evaluated_completion_samples"] == 0
            assert row["conditional_latest_completion_mae_minutes"] is None
        assert (
            row["clean_history_sessions"] == 0
        )  # interrupted/changed/sparse cycles never qualify training
