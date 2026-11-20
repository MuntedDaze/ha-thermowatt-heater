"""Multi-day expired-plan and refresh-failure outcomes never count as safe savings."""

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
        replay = importlib.import_module("pre_review_failure_replay")
    finally:
        sys.path.pop(0)
    return replay.results()


def test_failure_comparisons_are_reproducible_and_auth_locks_do_not_hammer_http(report):
    assert report == json.loads(
        (ROOT / "docs/evidence/FAILURE_RESULTS.json").read_text(encoding="utf-8")
    )
    assert len(report["runs"]) == 4
    for row in report["runs"]:
        fault = row["additional_failures"]
        assert fault["refresh_401_at"] is not None and fault["final_auth_mode"] == "blocked"
        assert fault["http_after_refresh_rejection"] == 0
        assert row["http_categories"]["password_login"] == 1
        assert row["http_total"] == sum(row["http_categories"].values())
        assert any("operator_recovery_required" in e["event"] for e in row["events"])
