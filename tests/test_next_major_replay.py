"""Reproduce seasonal comparisons with real policy/controller/bridge and fake I/O."""

import importlib
from datetime import datetime
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def comparison():
    sys.path.insert(0, str(ROOT / "tools"))
    replay = importlib.import_module("next_major_replay")
    try:
        return replay.results()
    finally:
        sys.path.pop(0)


def test_seasonal_results_reproduce_actual_http_and_energy_accounting(comparison):
    assert comparison == json.loads(
        (ROOT / "docs/history/next-major/SEASONAL_RESULTS.json").read_text()
    )
    assert len(comparison["reports"]) == 3
    physics = 315 * 4.186 / 3600
    for season in comparison["reports"]:
        for row in season["runs"]:
            assert row["http_total"] == sum(row["http_categories"].values())
            assert row["command_posts"] == row["http_categories"]["command"]
            energy = row["energy_kwh"]
            assert energy["unserved_draw"] == 0
            assert sum(energy[k] for k in ("peak", "off_peak", "solar")) == pytest.approx(
                (row["end_temperature_c"] - 45) * physics + energy["served_draw"] + energy["loss"],
                abs=0.000004,
            )
            assert row["additional_failures"]["http_after_refresh_rejection"] == 0
            assert row["maximum_healthy_status_age_minutes"] <= (
                721
                if row["strategy"] == "minimum"
                else 481
                if row["strategy"] == "smart"
                else 61
                if row["strategy"] == "fixed_60"
                else 31
            )


def test_request_savings_do_not_hide_target_outcomes_or_owner_detection(comparison):
    for season in comparison["reports"]:
        for ct in (False, True):
            rows = {r["strategy"]: r for r in season["runs"] if r["ct"] == ct}
            fixed = rows["fixed_30"]
            for strategy in ("smart", "minimum"):
                row = rows[strategy]
                assert row["http_total"] < fixed["http_total"] * 0.8
                assert row["command_posts"] == fixed["command_posts"]
                assert [d["required_target_reached"] for d in row["days"].values()] == [
                    d["required_target_reached"] for d in fixed["days"].values()
                ]
                assert row["persistent_owner_detection_minutes"] is not None
                assert row["persistent_owner_detection_minutes"] <= (
                    720 if strategy == "minimum" else 480
                )
                # A short app change may be missed, or caught by a useful read.
                # Validate the disclosed outcome against the actual owner hold;
                # never require the improved schedule to miss a real change.
                start = next(e["at"] for e in row["events"] if e["event"] == "transient_app_change")
                end = next(e["at"] for e in row["events"] if e["event"] == "transient_app_return")
                held = any(
                    d["state"] == "owner_override"
                    and datetime.fromisoformat(start)
                    <= datetime.fromisoformat(d["at"])
                    <= datetime.fromisoformat(end)
                    for d in row["decisions"]
                )
                assert row["transient_app_change_observed"] is held
                # Do not manufacture an exact cost-equality claim; bounded differences
                # are reported alongside actual service outcomes, not concealed.
                assert row["equal_terminal_cost_aud"] <= fixed["equal_terminal_cost_aud"] + 0.15
                if season["season"] == "dst_and_failures":
                    assert row["additional_failures"]["expired_lease_observed"] is True
                    assert row["additional_failures"]["final_auth_mode"] == "blocked"
