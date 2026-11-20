"""Actual HTTP savings must preserve service, economics and command safeguards."""

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
        replay = importlib.import_module("pre_review_replay")
    finally:
        sys.path.pop(0)
    return replay.results()


def test_comparison_is_reproducible_and_counts_every_actual_http_category(report):
    assert report == json.loads(
        (ROOT / "docs/history/pre-review/WEEK_RESULTS.json").read_text(encoding="utf-8")
    )
    assert len(report["runs"]) == 8
    physics = 315 * 4.186 / 3600
    for row in report["runs"]:
        assert row["http_total"] == sum(row["http_categories"].values())
        assert row["command_posts"] == row["http_categories"]["command"]
        energy = row["energy_kwh"]
        assert energy["served_draw"] == 45 and energy["unserved_draw"] == 0
        assert energy["peak"] + energy["off_peak"] + energy["solar"] == pytest.approx(
            (row["end_temperature_c"] - 45) * physics + energy["served_draw"] + energy["loss"],
            abs=0.000003,
        )
        assert row["end_stored_above_15_kwh"] + row["terminal_replenishment_kwh"] == pytest.approx(
            row["common_terminal_stored_kwh"], abs=0.000002
        )


@pytest.mark.parametrize("ct", [False, True])
def test_savings_do_not_purchase_less_service_or_conceal_failed_peak_lockout(report, ct):
    rows = {row["strategy"]: row for row in report["runs"] if row["ct"] == ct}
    fixed = rows["fixed_30"]
    for name in ("event_aware_60", "event_aware_90"):
        improved = rows[name]
        assert improved["http_total"] < fixed["http_total"] * 0.75
        assert improved["command_posts"] == fixed["command_posts"]
        assert improved["equal_terminal_cost_aud"] <= fixed["equal_terminal_cost_aud"] + 0.001
        assert (
            improved["energy_kwh"]["peak_unverified_lockout"]
            <= fixed["energy_kwh"]["peak_unverified_lockout"] + 0.00001
        )
        for day, actual in improved["days"].items():
            prior = fixed["days"][day]
            assert actual["required_target_reached"] == prior["required_target_reached"]
            if actual["at_peak_storage_shortfall_kwh"] is not None:
                assert (
                    actual["at_peak_storage_shortfall_kwh"]
                    <= prior["at_peak_storage_shortfall_kwh"] + 0.00001
                )
        assert (
            improved["required_planning_unknown_minutes"]
            <= fixed["required_planning_unknown_minutes"]
        )


def test_quiet_unknown_temperatures_and_detection_tradeoffs_are_visible(report):
    for row in report["runs"]:
        if row["strategy"].startswith("event_aware"):
            bound = int(row["strategy"].split("_")[-1])
            assert row["maximum_healthy_status_age_minutes"] <= bound + 1
            assert row["persistent_owner_detection_minutes"] <= bound + 1
            assert row["unknown_temperature_minutes"] > row["required_planning_unknown_minutes"]
            assert row["transient_app_change_observed"] is False
            if not row["ct"]:
                assert row["evaluated_completion_samples"] == 0
        if row["strategy"] == "fixed_60":
            assert row["required_planning_unknown_minutes"] > 300
