"""Summarise Home Assistant long-term statistics by day, week, month or year.

Reads data Home Assistant already stores; it keeps no database of its own and
never connects to Home Assistant. Workflow:

    python energy_monitoring/report.py --request
        prints a ``recorder.get_statistics`` action to paste into
        Developer tools > Actions (set the dates, run it, copy the response)

    python energy_monitoring/report.py response.yaml --period month
        prints a Markdown table from that saved response (YAML or JSON)
"""

import argparse
from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from energy_monitoring.calc import rollup  # noqa: E402
from energy_monitoring.mapping import (  # noqa: E402
    DEFAULT_MAP,
    hot_water_circuit,
    load,
    tracked_sources,
)


def columns(config: dict) -> list[tuple[str, str, str]]:
    """(statistic ID, column title, unit) for everything worth reporting."""
    grid, unit = config["grid"], config["currency"]
    result = [
        (config["solar"]["energy"], "Solar", "kWh"),
        ("sensor.em_house_energy", "House", "kWh"),
        (grid["import_energy"], "Import", "kWh"),
        (grid["export_energy"], "Export", "kWh"),
        ("sensor.em_solar_self_consumed_energy", "Solar used", "kWh"),
        ("sensor.em_grid_import_peak_energy", "Peak import", "kWh"),
        ("sensor.em_grid_import_off_peak_energy", "Off-peak import", "kWh"),
        ("sensor.em_grid_import_cost", "Import cost", unit),
        ("sensor.em_grid_export_earnings", "Feed-in", unit),
    ]
    if hot_water_circuit(config):
        result += [
            ("sensor.em_hot_water_grid_energy", "HW grid", "kWh"),
            ("sensor.em_hot_water_solar_energy", "HW solar", "kWh"),
            ("sensor.em_hot_water_grid_cost", "HW cost", unit),
            ("sensor.em_hot_water_solar_opportunity_cost", "HW solar opportunity", unit),
        ]
    result += [(s["energy"], s["name"], "kWh") for s in tracked_sources(config) if s["energy"]]
    result.append(("sensor.em_untracked_energy", "Untracked", "kWh"))
    return list(dict.fromkeys(result))


def request(config: dict) -> str:
    return yaml.safe_dump(
        {
            "action": "recorder.get_statistics",
            "data": {
                "start_time": "2026-01-01 00:00:00",
                "end_time": "2027-01-01 00:00:00",
                "period": "day",
                "types": ["change"],
                "statistic_ids": [statistic for statistic, _, _ in columns(config)],
            },
        },
        sort_keys=False,
    )


def daily_changes(rows: list[dict], zone: ZoneInfo) -> dict:
    """Daily ``change`` values keyed by the local date each day started on."""
    days = {}
    for row in rows:
        if row.get("change") is None:
            continue
        start = row["start"]
        moment = (
            datetime.fromtimestamp(start / 1000, zone)
            if isinstance(start, (int, float))
            else datetime.fromisoformat(str(start)).astimezone(zone)
        )
        days[moment.date()] = days.get(moment.date(), 0.0) + float(row["change"])
    return days


def table(response: dict, config: dict, period: str, zone: ZoneInfo) -> str:
    statistics = response.get("statistics", response)
    present = [column for column in columns(config) if statistics.get(column[0])]
    if not present:
        return "No matching statistics in the response."
    totals = {
        statistic: rollup(daily_changes(statistics[statistic], zone), period)
        for statistic, _, _ in present
    }
    labels = sorted({label for values in totals.values() for label in values})
    lines = [
        "| " + " | ".join([period.capitalize()] + [f"{t} ({u})" for _, t, u in present]) + " |",
        "| " + " | ".join(["---"] + ["---:"] * len(present)) + " |",
    ]
    for label in labels:
        cells = [
            f"{totals[statistic][label]:.2f}" if label in totals[statistic] else "–"
            for statistic, _, _ in present
        ]
        lines.append("| " + " | ".join([label] + cells) + " |")
    missing = [title for statistic, title, _ in columns(config) if not statistics.get(statistic)]
    if missing:
        lines += ["", "Not in the response: " + ", ".join(missing) + "."]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("response", nargs="?", type=Path)
    parser.add_argument("--period", choices=["day", "week", "month", "year"], default="month")
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--timezone", default="Australia/Hobart")
    parser.add_argument("--request", action="store_true")
    args = parser.parse_args(argv)
    config = load(args.map)
    if args.request:
        print(request(config))
        return 0
    if not args.response:
        parser.error("give a saved response file, or --request")
    response = yaml.safe_load(args.response.read_text(encoding="utf-8")) or {}
    print(table(response, config, args.period, ZoneInfo(args.timezone)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
