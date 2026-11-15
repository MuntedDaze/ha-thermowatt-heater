"""Focused fixed30/fixed60/event-aware60/event-aware90 actual-worker comparison."""

import argparse
import json
from pathlib import Path

from final_week_replay import results as replay


def results():
    report = replay(
        [
            ("fixed_30", "fixed_30", False, 60),
            ("fixed_60", "fixed_60", False, 60),
            ("event_aware_60", "actual_adaptive", True, 60),
            ("event_aware_90", "actual_adaptive", True, 90),
        ]
    )
    report["schema_version"] = 2
    report["assumptions"]["event_aware"] = (
        "Explicit synthetic qualification/enables; healthy quiet confirmed baseline/OFF "
        "owner checks60/90min; temperature expires45min; unchanged60s bridge command prior "
        "and bounded confirmation. Refresh heuristic unchanged; no vendor lifetime inferred."
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(results(), indent=2) + "\n", encoding="utf-8")
