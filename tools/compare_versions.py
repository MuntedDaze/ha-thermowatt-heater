"""Before/after: frozen 0.3.0 planner vs current 0.4.0 on IDENTICAL synthetic inputs.

Offline and deterministic. 0.3.0 is loaded from the byte-identical fixture of
the installed version (tools/readiness/fixtures/thermann_shadow_0_3_0).

    python tools/compare_versions.py   # rewrites docs/history/controller/COMPARISON_0_3_0_VS_0_4_0.md
"""

from datetime import datetime, timedelta
import importlib
from pathlib import Path
import sys
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/history/controller/COMPARISON_0_3_0_VS_0_4_0.md"


def package(name, path):
    module = ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module
    return lambda sub: importlib.import_module(f"{name}.{sub}")


old = package("_v030", ROOT / "tools/readiness/fixtures/thermann_shadow_0_3_0")
new = package("_v040", ROOT / "custom_components/thermann_shadow")
m3, c3, cy3, d3 = old("model"), old("config"), old("cycles"), old("decision")
m4, c4, s4, g4, h4 = new("model"), new("config"), new("strategy"), new("goals"), new("heater_state")


def local(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=m4.HOBART).astimezone(m4.UTC)


def old_decision(now, temp, export_kw, forecast_surplus=None, poll_age=5, report_age=0):
    """0.3.0: evaluate -> CyclePolicy -> decide, as installed (deployed options)."""
    settings, tariffs = c3.parse_options({"forecast_enabled": forecast_surplus is not None})
    poll = now - timedelta(minutes=poll_age)
    observed = now - timedelta(minutes=report_age)  # entity write time (MQTT: last change)
    readings = {
        "temperature": m3.Reading(temp, observed, "°C"),
        "target": m3.Reading(70, observed, "°C"),
        "mode": m3.Reading("Schedule", observed),
        "cloud_health": m3.Reading("ok", observed),
        "last_poll": m3.Reading(poll.isoformat(), now),
        "grid": m3.Reading(export_kw * 1000, now, "W"),
    }
    slots = ()
    if forecast_surplus is not None:
        slots = (m3.Forecast(now, now + timedelta(hours=12), forecast_surplus),)
    plan = m3.evaluate(now, now - timedelta(hours=2), readings, settings, tariffs, slots)
    policy = cy3.CyclePolicy()
    result = policy.step(now, plan, settings, tariffs, slots, now)
    code, label, _ = d3.decide(
        plan,
        result,
        policy.active,
        slots != (),
        "published_pv_and_house_load" if slots else "disabled",
        settings,
    )
    return {
        "label": label,
        "deadline": plan.deadline.astimezone(m4.HOBART).strftime("%a %H:%M")
        if plan.deadline
        else "—",
        "goal_c": plan.planning_target_c,
        "now_cost": result.get("continuing_cost_aud"),
    }


def new_decision(now, temp, house_kw, pv_kw, forecast_pv=None, element="unknown", poll_age=5):
    settings, tariffs = c4.parse_options({"forecast_enabled": forecast_pv is not None})
    state = h4.HeaterState(state=element)
    low, high = h4.base_load(house_kw, state)
    goals = g4.upcoming_goals(now, settings, tariffs)[:2]
    if poll_age > settings.status_max_age_minutes:
        return {"label": "DATA UNAVAILABLE", "deadline": "—", "goal_c": None, "now_cost": None}
    horizon = max(goal.deadline for goal in goals)
    series = ()
    if forecast_pv is not None:
        series = ((now, horizon + timedelta(hours=1), forecast_pv),)
    slots = s4.build_slots(now, horizon, settings, tariffs, pv_kw, (low, high), high, series, ())
    pessimistic = None
    if element == "unknown":
        pessimistic = s4.build_slots(
            now, horizon, settings, tariffs, pv_kw, (high, high), high, series, ()
        )
    result = s4.assess(
        now,
        temp,
        goals,
        slots,
        settings,
        element,
        forecast_pv is not None,
        pessimistic_slots=pessimistic,
    )
    best = result.plans.get("best_overall")
    _, label, _, _ = s4.compose_with_heater(
        (result.code, result.label, result.explanation, result.confidence),
        element,
        best.start if best else None,
        "high",
    )
    goal = goals[0]
    return {
        "label": label,
        "range": result.heat_now_cost_range_aud,
        "deadline": goal.deadline.astimezone(m4.HOBART).strftime("%a %H:%M"),
        "goal_c": goal.target_c,
        "now_cost": result.heat_now_cost_aud,
        "best_cost": result.best_cost_aud,
        "saving": result.saving_by_waiting_aud,
    }


CASES = [
    # name, now, temp, house kW, pv AC kW, forecast PV kW (None = off), element, note
    (
        "Observed 11 Nov 11:42, element ON",
        local(2026, 11, 11, 11, 42),
        52,
        3.90,
        4.97,
        3.43,
        "on",
        "native heating already absorbing solar",
    ),
    (
        "Same, element OFF (other 3.9 kW load)",
        local(2026, 11, 11, 11, 42),
        52,
        3.90,
        4.97,
        3.43,
        "off",
        "",
    ),
    ("Same, element UNKNOWN", local(2026, 11, 11, 11, 42), 52, 3.90, 4.97, 3.43, "unknown", ""),
    (
        "Depleted 16 °C at 03:00 (DST weekday)",
        local(2026, 11, 11, 3),
        16,
        0.65,
        0.0,
        None,
        "off",
        "morning",
    ),
    (
        "41 °C at 06:00, summer weekday",
        local(2026, 11, 10, 6),
        41,
        0.6,
        0.2,
        None,
        "off",
        "40 vs 42 °C",
    ),
    (
        "1 kW export, off-peak 12:00",
        local(2026, 11, 10, 12),
        55,
        0.9,
        1.9,
        1.9,
        "off",
        "partial solar",
    ),
    (
        "1 kW export, peak 09:00 (AEDT)",
        local(2026, 11, 10, 9),
        55,
        0.9,
        1.9,
        1.9,
        "off",
        "peak partial solar",
    ),
    (
        "Partial now, full solar forecast later",
        local(2026, 11, 10, 11),
        55,
        0.8,
        1.1,
        4.3,
        "off",
        "",
    ),
    (
        "Winter weekday 13:00, 60 °C",
        local(2026, 6, 9, 13),
        60,
        0.6,
        1.5,
        1.5,
        "off",
        "16:00 deadline",
    ),
    (
        "Summer weekday 13:00, 60 °C",
        local(2026, 11, 10, 13),
        60,
        0.6,
        1.5,
        1.5,
        "off",
        "17:00 deadline",
    ),
    ("Saturday 10:00, 60 °C", local(2026, 11, 14, 10), 60, 0.6, 3.5, 3.5, "off", "no peak"),
]


def run():
    rows = []
    for name, now, temp, house, pv, fpv, element, note in CASES:
        export = pv - house
        forecast_surplus = None if fpv is None else max(0.0, fpv * 0.75 - house * 1.25 - 0.3)
        before = old_decision(now, temp, export, forecast_surplus)
        after = new_decision(now, temp, house, pv, fpv, element)
        rows.append({"case": name, "note": note, "before": before, "after": after})
    # Stage 1 F1: unchanged MQTT payload, entity last written 50 min ago, poll 5 min ago.
    now = local(2026, 11, 11, 12, 2)
    before = old_decision(now, 55, 1.2, None, poll_age=5, report_age=50)
    after = new_decision(now, 55, 3.9, 4.97, None, "on", poll_age=5)
    rows.append(
        {
            "case": "Unchanged MQTT payload (written 50 min ago, poll 5 min ago)",
            "note": "Stage 1 F1",
            "before": before,
            "after": after,
        }
    )
    return rows


def markdown(rows):
    lines = [
        "# Shadow Planner 0.3.0 vs 0.4.0 — identical synthetic inputs",
        "",
        "Generated by `python tools/compare_versions.py` (reproduced in tests). 0.3.0 is the "
        "frozen installed code; 0.4.0 is this candidate. Costs are AUD for the remaining "
        "required energy; *now* means starting now for at least the minimum cycle; with the heater state UNKNOWN the heat-now cost is a range. Synthetic inputs, not measurements.",
        "",
        "| Case | 0.3.0 says | 0.3.0 deadline / goal | 0.3.0 now $ | 0.4.0 says | 0.4.0 deadline / goal | 0.4.0 now $ | best $ | saving by waiting $ |",
        "|---|---|---|---:|---|---|---:|---:|---:|",
    ]
    for row in rows:
        b, a = row["before"], row["after"]

        def money(value):
            return "—" if value is None else f"{value:.2f}"

        now_cost = money(a["now_cost"])
        if a.get("range") and a["range"][1] - a["range"][0] > 0.005:
            now_cost = f"{a['range'][0]:.2f}-{a['range'][1]:.2f}"
        lines.append(
            f"| {row['case']} | {b['label']} | {b['deadline']} / {b['goal_c']} | "
            f"{money(b['now_cost'])} | {a['label']} | {a['deadline']} / {a['goal_c']} | "
            f"{now_cost} | {money(a.get('best_cost'))} | {money(a.get('saving'))} |"
        )
    return "\n".join(lines) + "\n"


def main():
    text = markdown(run())
    OUT.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
