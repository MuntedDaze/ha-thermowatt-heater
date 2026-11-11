"""Replay numeric HA-history/scenario snapshots offline; never access Home Assistant."""

from dataclasses import asdict
from datetime import timedelta
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType


def replay(path):
    root = Path(__file__).resolve().parents[1]
    package = ModuleType("_thermann_replay")
    package.__path__ = [str(root / "custom_components/thermann_shadow")]
    sys.modules[package.__name__] = package
    model = importlib.import_module(f"{package.__name__}.model")
    config = importlib.import_module(f"{package.__name__}.config")
    if path.stat().st_size > 2_000_000:
        raise ValueError
    data = json.loads(path.read_text(encoding="utf-8"))
    settings, tariffs = config.parse_options(data.get("options", {}))
    rows = data["rows"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10000:
        raise ValueError
    boot = model.timestamp(rows[0]["at"]) - timedelta(seconds=1)
    previous, results = boot, []
    for row in rows:
        now = model.timestamp(row["at"])
        if now <= previous:
            raise ValueError
        previous = now
        values = {
            "temperature": (row.get("temperature"), "°C"),
            "target": (row.get("target", 70), "°C"),
            "mode": (row.get("mode", "Schedule"), None),
            "grid": (row.get("grid_w"), "W"),
            "cloud_health": (row.get("cloud_health", "ok"), None),
            "last_poll": (
                (now - timedelta(minutes=model.number(row.get("poll_age_minutes", 0)))).isoformat(),
                None,
            ),
        }
        readings = {
            key: model.Reading(value, now, unit)
            for key, (value, unit) in values.items()
            if value is not None
        }
        plan = model.evaluate(now, boot, readings, settings, tariffs)
        results.append({"at": now.isoformat(), "plan": asdict(plan)})
    return {"replay_only": True, "live_requests": 0, "heater_commands": 0, "results": results}


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError
        print(
            json.dumps(replay(Path(sys.argv[1])), default=lambda value: value.isoformat(), indent=2)
        )
    except (ValueError, KeyError, TypeError, OSError, OverflowError):
        print("Replay rejected: code=scenario_input_invalid.", file=sys.stderr)
        raise SystemExit(1) from None
