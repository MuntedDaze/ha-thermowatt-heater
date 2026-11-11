"""Replay a LOCAL COPY of the Home Assistant recorder through the real runtime.

Read-only and offline: opens the SQLite file with mode=ro, never contacts HA,
Thermann or EMHASS, and prints AGGREGATED results only. Never commit the
database itself (it is private household data).

Faithful to HA behaviour that matters here: an entity's report time only
advances when the recorder stored a state write, so unchanged MQTT payloads
look exactly as they did live (Stage 1 finding F1).

    python tools/replay_history.py --db COPY.db --start 2026-11-10T14:25 \
        --end 2026-11-11T12:20 [--json out.json] [--controller-dry-run]

--controller-dry-run (0.5.0) also feeds every minute's advice through the real
planner->controller boundary (control_plan.desire_from_advice) and the
controller's poll alignment and hysteresis rule, assuming each command is
confirmed at its poll. It is OPEN LOOP: the recorded heater followed its native
Schedule, so this estimates command counts and timing on real data; it is not
a prediction of temperatures under control. Nothing is ever published.
"""

import argparse
from bisect import bisect_right
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "custom_components/thermann_shadow"
SNAPSHOT = ROOT / "audit/thermann_shadow/config_entry.json"


class Clock:
    now = None


def load_runtime():
    util = ModuleType("homeassistant.util")
    util.dt = SimpleNamespace(utcnow=lambda: Clock.now)
    ha = ModuleType("homeassistant")
    ha.__path__ = []
    sys.modules.setdefault("homeassistant", ha)
    sys.modules["homeassistant.util"] = util
    package = ModuleType("_replay_shadow")
    package.__path__ = [str(PACKAGE)]
    sys.modules[package.__name__] = package
    config = importlib.import_module(f"{package.__name__}.config")
    model = importlib.import_module(f"{package.__name__}.model")
    spec = importlib.util.spec_from_file_location(
        f"{package.__name__}.runtime", PACKAGE / "runtime.py"
    )
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    return config, model, runtime


class History:
    """Per-entity step histories: (write_time, report_time, state, attributes)."""

    def __init__(self, db_path, entities, start, end):
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self.rows = {}
        for entity in entities:
            rows = db.execute(
                """select s.state, s.last_updated_ts, coalesce(s.last_reported_ts, s.last_updated_ts),
                          a.shared_attrs
                   from states s join states_meta m on m.metadata_id = s.metadata_id
                   left join state_attributes a on a.attributes_id = s.attributes_id
                   where m.entity_id = ? and s.last_updated_ts <= ? order by s.last_updated_ts""",
                (entity, end.timestamp()),
            ).fetchall()
            self.rows[entity] = [(r[1], r[2], r[0], json.loads(r[3]) if r[3] else {}) for r in rows]
            self.rows[entity + "#t"] = [r[0] for r in self.rows[entity]]
        db.close()

    def state(self, entity, at, model):
        rows = self.rows.get(entity)
        if not rows:
            return None
        index = bisect_right(self.rows[entity + "#t"], at.timestamp()) - 1
        if index < 0:
            return None
        written, reported, value, attrs = rows[index]
        reported_at = datetime.fromtimestamp(min(reported, at.timestamp()), model.UTC)
        return SimpleNamespace(
            state=value,
            attributes=attrs,
            last_reported=reported_at,
            last_updated=datetime.fromtimestamp(written, model.UTC),
        )


def replay(db_path, start, end, detail_at=(), dry_run=False):
    config, model, runtime_module = load_runtime()
    control_plan = goals = None
    if dry_run:
        package = sys.modules[runtime_module.__name__.rsplit(".", 1)[0]]
        control_plan = importlib.import_module(f"{package.__name__}.control_plan")
        goals = importlib.import_module(f"{package.__name__}.goals")
    dry = {"permitted": False, "poll": None, "commands": [], "skipped_hysteresis": 0}
    saved = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["options"]
    sources = dict(saved["sources"])
    sources["pv_ac"] = config.DEFAULT_PV_AC
    # Template forecast inputs are excluded from the recorder; rebuild them from
    # the recorded EMHASS sensors and the generation helper (as the template does).
    pv_f, load_f, helper = (
        "sensor.p_pv_forecast",
        "sensor.p_load_forecast",
        ("input_datetime.emhass_forecast_generated"),
    )
    entities = {value for value in sources.values() if value} | {pv_f, load_f, helper}
    history = History(db_path, entities, start, end)

    class States:
        def __init__(self):
            self.at = None

        def get(self, entity):
            if entity in {sources.get("forecast_pv"), sources.get("forecast_load")}:
                base = history.state(
                    pv_f if entity == sources["forecast_pv"] else load_f, self.at, model
                )
                stamp = history.state(helper, self.at, model)
                if base is None or stamp is None or "timestamp" not in stamp.attributes:
                    return None
                generated = datetime.fromtimestamp(stamp.attributes["timestamp"], model.UTC)
                return SimpleNamespace(
                    state=base.state,
                    attributes={
                        "unit_of_measurement": "W",
                        "forecasts": base.attributes.get("forecasts") or [],
                        "forecast_generated_at": generated.astimezone(model.HOBART).isoformat(),
                    },
                    last_reported=base.last_reported,
                    last_updated=base.last_updated,
                )
            return history.state(entity, self.at, model)

    states = States()
    hass = SimpleNamespace(
        states=states, config=SimpleNamespace(units=SimpleNamespace(temperature_unit="°C"))
    )
    # Apply the 0.4.0 entry migration exactly as HA would on upgrade.
    if saved.get("morning_threshold_c") == config.LEGACY_MORNING_THRESHOLD_C:
        saved = {**saved, "morning_threshold_c": 42.0}
    settings, tariffs = config.parse_options(saved)
    Clock.now = start - timedelta(minutes=1)
    states.at = Clock.now
    instance = runtime_module.ShadowRuntime(hass, sources, settings, tariffs)
    instance.set_native_reference(saved)
    rows = []
    now = start
    while now <= end:
        Clock.now = states.at = now
        instance.update(now)
        values, details = instance.values, instance.details
        rows.append(
            {
                "at": now.astimezone(model.HOBART).strftime("%d %H:%M"),
                "state": instance.plan.state,
                "decision": values.get("decision"),
                "label": values.get("recommendation"),
                "heater": values.get("heater_element_state"),
                "heater_confidence": values.get("heater_state_confidence"),
                "temperature": values.get("temperature"),
                "base_kw": values.get("base_load_kw"),
                "surplus_kw": values.get("current_solar_surplus_kw"),
                "heat_now_cost": values.get("continuing_cost_aud"),
                "best_cost": values.get("later_cost_aud"),
                "saving_by_waiting": values.get("waiting_saving_aud"),
                "confidence": values.get("decision_confidence"),
                "reasons": list(details.get("reasons", [])),
            }
        )
        if rows[-1]["at"] in detail_at:
            rows[-1]["detail"] = {
                key: details.get(key)
                for key in (
                    "goals",
                    "requirements_kwh",
                    "strategies",
                    "fallback_starts",
                    "heater_state",
                    "load",
                    "decision_explanation",
                )
            }
        if dry_run:
            change = goals.next_tariff_change(now, tariffs, settings.tariff_clock)
            peak = change[0] if change and change[1].kind == "peak" else None
            desire = control_plan.desire_from_advice(
                now,
                instance.advice,
                dry["permitted"],
                30,
                peak,
                instance.advice.heater.state if instance.advice else "unknown",
            )
            rows[-1]["desire"] = desire.action
            poll = states.get(sources["last_poll"])
            poll = poll.state if poll is not None else None
            new_poll, dry["poll"] = poll != dry["poll"] and poll is not None, poll
            want = {"permit": True, "park": False}.get(desire.action, dry["permitted"])
            if new_poll and want != dry["permitted"]:
                reading = values.get("temperature")
                if want and (reading is None or reading > 62):
                    dry["skipped_hysteresis"] += 1
                else:
                    dry["permitted"] = want
                    dry["commands"].append(
                        (rows[-1]["at"], "Manual:70" if want else "Auto", desire.reason)
                    )
        now += timedelta(minutes=1)
    if dry_run:
        rows.append({"controller_dry_run": dry})
    return rows


def _ranges(stamps):
    """Contiguous minute ranges from 'DD HH:MM' stamps (already in time order)."""
    ranges = []
    previous = None
    for stamp in stamps:
        minute = int(stamp[:2]) * 1440 + int(stamp[3:5]) * 60 + int(stamp[6:8])
        if ranges and previous is not None and minute == previous + 1:
            ranges[-1][1] = stamp
        else:
            ranges.append([stamp, stamp])
        previous = minute
    return ranges


def summarise(rows):
    dry = rows[-1].get("controller_dry_run") if rows else None
    if dry is not None:
        rows = rows[:-1]
    total = len(rows)
    blocked = sum(1 for row in rows if row["state"].startswith("shadow_blocked"))
    decisions = []
    for row in rows:
        if not decisions or decisions[-1][1] != row["label"]:
            decisions.append((row["at"], row["label"], row["decision"]))
    heater = {}
    for row in rows:
        heater[row["heater"]] = heater.get(row["heater"], 0) + 1
    transitions = []
    for row in rows:
        key = (row["heater"], row["heater_confidence"])
        if not transitions or transitions[-1][1] != key:
            transitions.append((row["at"], key, row["temperature"], row["base_kw"]))
    suspect = [row["at"] for row in rows if "meter_reading_suspect" in row["reasons"]]
    return {
        "heater_transitions": transitions,
        "meter_suspect_minutes": _ranges(suspect),
        "minutes": total,
        "available_fraction": round(1 - blocked / total, 4) if total else None,
        "blocked_minutes": blocked,
        "blocked_reasons": sorted(
            {
                tuple(r["reasons"]) and r["reasons"][0]
                for r in rows
                if r["state"].startswith("shadow_blocked")
            }
        ),
        "heater_state_minutes": heater,
        "decision_changes": decisions,
        **({"controller_dry_run": dry} if dry is not None else {}),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--json")
    parser.add_argument("--at", action="append", default=[], help="Hobart 'DD HH:MM' rows to print")
    parser.add_argument("--controller-dry-run", action="store_true")
    args = parser.parse_args()
    _, model, _ = load_runtime()

    def parse(text):
        return datetime.fromisoformat(text).replace(tzinfo=model.HOBART).astimezone(model.UTC)

    rows = replay(
        args.db, parse(args.start), parse(args.end), set(args.at), args.controller_dry_run
    )
    result = {
        "summary": summarise(rows),
        "rows_at": [row for row in rows if row.get("at") in args.at],
    }
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    print(json.dumps(result, indent=1, default=str))


if __name__ == "__main__":
    main()
