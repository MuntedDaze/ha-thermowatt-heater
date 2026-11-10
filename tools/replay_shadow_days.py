"""Closed-loop synthetic DAYS through the real planner chain. Offline; never HA/HTTP.

Every minute: synthetic PV/house -> measured grid -> forecast adapter ->
evaluate() -> CyclePolicy -> decide(). A HYPOTHETICAL future executor is assumed
to follow the simulated cycle exactly with a separately VERIFIED 3 kW element, so
the tank warms and the meter sees the load. That executor does not exist; these
are reproducible design checks, not heater tests or promised savings.

Simplifications (stated in the report): uniform tank, no draw-off or standing
loss during the window, cloud polls every 30 min with whole-degree readings,
no native Schedule heating (the executor would replace it).
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import importlib
import json
import math
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
package = ModuleType("_day_replay")
package.__path__ = [str(ROOT / "custom_components/thermann_shadow")]
sys.modules[package.__name__] = package
model = importlib.import_module(f"{package.__name__}.model")
config = importlib.import_module(f"{package.__name__}.config")
cycles = importlib.import_module(f"{package.__name__}.cycles")
forecast = importlib.import_module(f"{package.__name__}.forecast")
decision = importlib.import_module(f"{package.__name__}.decision")

DEGREES_PER_MINUTE = model.ELEMENT_KW / 60 / model.TANK_KWH_PER_C
# Thermann reports whole degrees, so a goal is met within half a degree of
# reporting resolution (69.6 °C is reported as 70 °C, as the planner sees it).
RESOLUTION_C = 0.5


@dataclass
class Case:
    name: str
    description: str
    start: tuple  # (year, month, day, hour, minute) Hobart local
    hours: float
    temperature: float
    peak_kw: float = 4.5  # clear-sky net-of-nothing PV peak
    sun: tuple = (6.0, 20.0)  # local sunrise/sunset hours
    house_kw: float = 0.5
    clouds: tuple = ()  # ((start_h, end_h, factor), ...) applied to ACTUAL PV
    forecast_clouds: tuple | None = None  # what the forecast believes (None = truth)
    loads: tuple = ()  # ((start_h, end_h, extra_kw), ...) actual household spikes
    forecast: bool = False
    forecast_age_hours: float = 0.0  # >0 makes every published forecast stale
    poll_outage: tuple = ()  # (start_h, end_h): no new cloud poll in this period
    deembed: bool = True  # future executor de-embeds its VERIFIED element load
    options: dict = field(default_factory=dict)


def local(parts, hours=0.0):
    year, month, day, hour, minute = parts
    return (
        datetime(year, month, day, hour, minute, tzinfo=model.HOBART) + timedelta(hours=hours)
    ).astimezone(model.UTC)


def hour_of(at):
    value = at.astimezone(model.HOBART)
    return value.hour + value.minute / 60


def pv_kw(case, at, clouds):
    rise, setting = case.sun
    hour = hour_of(at)
    if not rise < hour < setting:
        return 0.0
    value = case.peak_kw * math.sin(math.pi * (hour - rise) / (setting - rise))
    for start, end, factor in clouds:
        if start <= hour < end:
            value *= factor
    return round(max(0.0, value), 4)


def house_kw(case, at, actual=True):
    hour = hour_of(at)
    extra = sum(kw for start, end, kw in case.loads if start <= hour < end) if actual else 0
    return case.house_kw + extra


def published(case, now, generated):
    """Owner template sensors: EMHASS-shaped PV and load forecasts, 30-min steps."""
    clouds = case.clouds if case.forecast_clouds is None else case.forecast_clouds
    base = generated.replace(minute=0 if generated.minute < 30 else 30, second=0, microsecond=0)
    points = [base + timedelta(minutes=30 * i) for i in range(48)]

    def state(key, values):
        return SimpleNamespace(
            state="0",
            attributes={
                "unit_of_measurement": "kW",
                "forecast_generated_at": generated.isoformat(),
                "forecasts": [
                    {"date": at.isoformat(), key: f"{value:.3f}"}
                    for at, value in zip(points, values, strict=True)
                ],
            },
        )

    # Mean over each 30-minute step, like a real forecast provider.
    def mean(function, at):
        return sum(function(at + timedelta(minutes=m)) for m in range(0, 30, 5)) / 6

    pv = state("p_pv_forecast", [mean(lambda t: pv_kw(case, t, clouds), at) for at in points])
    load = state("p_load_forecast", [mean(lambda t: house_kw(case, t, False), at) for at in points])
    return pv, load


def simulate(case):
    settings, tariffs = config.parse_options({**case.options, "forecast_enabled": case.forecast})
    start = local(case.start)
    boot = start - timedelta(minutes=1)
    policy = cycles.CyclePolicy()
    temperature = case.temperature
    poll_value, poll_at = round(temperature), start
    heating = False
    export_minutes = 0
    pv_history = []
    publications = {}  # the owner's template republishes only on a new generation
    totals = {"energy": 0.0, "solar": 0.0, "import": 0.0, "cost": 0.0, "grid_cost": 0.0}
    decisions, first_start, goals = [], None, []
    for minute in range(int(case.hours * 60) + 1):
        now = start + timedelta(minutes=minute)
        hour = (now - start).total_seconds() / 3600
        outage = case.poll_outage and case.poll_outage[0] <= hour < case.poll_outage[1]
        if minute % 30 == 0 and not outage:
            poll_value, poll_at = round(temperature), now
        pv, house = pv_kw(case, now, case.clouds), house_kw(case, now)
        element = model.ELEMENT_KW if heating else 0.0
        measured = pv - house - element
        planner_grid = cycles.baseline_export(measured, element) if case.deembed else measured
        export_minutes = (
            export_minutes + 1
            if planner_grid >= settings.min_solar_kw + settings.export_headroom_kw
            else 0
        )
        readings = {
            "temperature": model.Reading(poll_value, poll_at, "°C"),
            "target": model.Reading(70, poll_at, "°C"),
            "mode": model.Reading("Schedule", poll_at),
            "cloud_health": model.Reading("ok", poll_at),
            "last_poll": model.Reading(poll_at.isoformat(), poll_at),
            "grid": model.Reading(round(planner_grid * 1000, 1), now, "W"),
        }
        pv_history = [(at, kw) for at, kw in pv_history if now - at <= timedelta(minutes=15)]
        pv_history.append((now, pv))
        slots, source = (), "disabled"
        if case.forecast:
            generated = now.replace(minute=0, second=0, microsecond=0) - timedelta(
                hours=case.forecast_age_hours
            )
            if generated not in publications:
                publications[generated] = published(case, now, generated)
            pv_state, load_state = publications[generated]
            result = forecast.build_forecast(
                now,
                boot - timedelta(hours=case.forecast_age_hours + 1),
                settings,
                pv_state,
                load_state,
                sum(kw for _, kw in pv_history) / len(pv_history),
            )
            slots, source = result.slots, result.source
        plan = model.evaluate(
            now,
            boot,
            readings,
            settings,
            tariffs,
            slots,
            solar_confirmed=export_minutes >= settings.solar_hold_minutes,
        )
        if plan.deadline and (not goals or goals[-1][0] != plan.deadline):
            goals.append((plan.deadline, plan.planning_target_c))
        override = "thermostat_satisfied" if temperature >= 70 else None
        result = policy.step(now, plan, settings, tariffs, slots, now, override)
        code, _, _ = decision.decide(plan, result, policy.active, case.forecast, source, settings)
        if not decisions or decisions[-1][1] != code:
            decisions.append((now.astimezone(model.HOBART).strftime("%H:%M"), code))
        heating = policy.active
        if heating:
            first_start = first_start or now
            solar = min(model.ELEMENT_KW, max(0.0, pv - house))
            rate = model.tariff_at(now, tariffs, settings.tariff_clock).rate
            totals["energy"] += model.ELEMENT_KW / 60
            totals["solar"] += solar / 60
            totals["import"] += (model.ELEMENT_KW - solar) / 60
            totals["cost"] += (
                (model.ELEMENT_KW - solar) * rate + solar * settings.feed_in_rate
            ) / 60
            totals["grid_cost"] += model.ELEMENT_KW * rate / 60
            temperature += DEGREES_PER_MINUTE
        # Record comfort at each goal deadline the moment it is reached.
        for deadline, target in goals:
            if deadline == now:
                goals_met.setdefault(case.name, []).append(
                    {
                        "deadline": deadline.astimezone(model.HOBART).strftime("%a %d %b %H:%M"),
                        "goal_c": target,
                        "tank_c": round(temperature, 1),
                        "met": temperature + RESOLUTION_C >= target,
                    }
                )
    met = goals_met.pop(case.name, [])
    return {
        "description": case.description,
        "comfort": met,
        "comfort_met": all(item["met"] for item in met) if met else None,
        "final_tank_c": round(temperature, 1),
        "energy_kwh": round(totals["energy"], 3),
        "solar_kwh": round(totals["solar"], 3),
        "import_kwh": round(totals["import"], 3),
        "cost_aud": round(totals["cost"], 3),
        "same_energy_all_grid_aud": round(totals["grid_cost"], 3),
        "cycles": policy.starts,
        "stops": policy.stops,
        "suppressed_switching_episodes": policy.suppressed_edges,
        "first_start": first_start.astimezone(model.HOBART).strftime("%H:%M")
        if first_start
        else None,
        "decisions": decisions,
    }


goals_met: dict = {}
SUMMER, WINTER, WEEKEND = (2026, 11, 10), (2026, 6, 9), (2026, 11, 14)
WINTER_SUN = (7.5, 17.0)


def day(date, hour, minute=0):
    return (*date, hour, minute)


CASES = [
    Case(
        "partial_2kw_measured_only",
        "Steady ~2 kW net surplus, forecasts OFF (defaults).",
        day(SUMMER, 9),
        8,
        55,
        peak_kw=2.5,
        sun=(0.1, 23.9),
        forecast=False,
    ),
    *[
        Case(
            f"surplus_{kw}kw_forecast",
            f"Steady ~{kw} kW net surplus, accurate forecast.",
            day(SUMMER, 9),
            8,
            55,
            peak_kw=kw + 0.5,
            sun=(0.1, 23.9),
            forecast=True,
        )
        for kw in (1, 2, 3, 4)
    ],
    Case(
        "clear_morning_cloudy_afternoon",
        "Sunny until 12:30 then 80% cloud; forecast knows.",
        day(SUMMER, 9),
        8,
        50,
        clouds=((12.5, 24, 0.2),),
        forecast=True,
    ),
    Case(
        "cloudy_morning_sunny_afternoon",
        "Heavy cloud until 12:00, then clear; forecast knows.",
        day(SUMMER, 9),
        8,
        50,
        clouds=((0, 12, 0.15),),
        forecast=True,
    ),
    Case(
        "forecast_sun_fails",
        "Forecast clear all day; reality 85% cloud. Fallback must hold.",
        day(SUMMER, 9),
        8,
        50,
        clouds=((0, 24, 0.15),),
        forecast_clouds=(),
        forecast=True,
    ),
    Case(
        "household_load_spike",
        "Clear day; 2.5 kW appliance 12:00-13:00 not forecast.",
        day(SUMMER, 9),
        8,
        50,
        loads=((12, 13, 2.5),),
        forecast=True,
    ),
    Case(
        "solar_drop_mid_cycle",
        "Clear day with a 30-minute 90% cloud at 11:30.",
        day(SUMMER, 9),
        8,
        45,
        clouds=((11.5, 12, 0.1),),
        forecast=True,
    ),
    Case(
        "depleted_winter_tank",
        "Winter weekday, 20°C tank at 09:00; little solar.",
        day(WINTER, 9),
        7,
        20,
        peak_kw=2.0,
        sun=WINTER_SUN,
        forecast=True,
    ),
    Case(
        "warm_morning_tank",
        "45°C at 00:30: above the 40°C morning threshold.",
        day(SUMMER, 0, 30),
        6.5,
        45,
    ),
    Case(
        "cold_morning_tank",
        "35°C at 00:30: off-peak top-up to 40°C by 07:00.",
        day(SUMMER, 0, 30),
        6.5,
        35,
    ),
    Case(
        "target_65",
        "Afternoon storage target 65°C, clear day.",
        day(SUMMER, 9),
        8,
        50,
        forecast=True,
        options={"target_c": 65},
    ),
    Case(
        "target_70",
        "Afternoon storage target 70°C, same clear day.",
        day(SUMMER, 9),
        8,
        50,
        forecast=True,
    ),
    Case(
        "winter_weekday",
        "Winter clear day, peak at 16:00 Hobart.",
        day(WINTER, 9),
        7,
        50,
        peak_kw=3.5,
        sun=WINTER_SUN,
        forecast=True,
    ),
    Case(
        "weekend_summer",
        "Saturday: off-peak all day, comfort time 16:00.",
        day(WEEKEND, 9),
        7,
        50,
        forecast=True,
    ),
    Case(
        "dst_start_morning",
        "Sun 4 Oct 2026 (clocks forward at 02:00), 35°C at 00:30.",
        (2026, 10, 4, 0, 30),
        5.5,
        35,
    ),
    Case(
        "dst_end_morning",
        "Sun 5 Apr 2026 (clocks back at 03:00), 35°C at 00:30.",
        (2026, 4, 5, 0, 30),
        7.5,
        35,
    ),
    Case(
        "stale_forecast",
        "Forecast published 3 h old: ignored; conservative fallback.",
        day(SUMMER, 9),
        8,
        50,
        forecast=True,
        forecast_age_hours=3,
    ),
    Case(
        "cloud_poll_outage",
        "No new Thermann poll 11:00-13:00 (data unavailable).",
        day(SUMMER, 9),
        8,
        50,
        forecast=True,
        poll_outage=(2, 4),
    ),
    Case(
        "insufficient_off_peak_time",
        "20°C at 14:00 summer weekday: cannot reach 70°C by 17:00.",
        day(SUMMER, 14),
        3,
        20,
        forecast=True,
    ),
    Case(
        "no_deembedding_naive_meter",
        "Clear 4 kW day, executor IGNORES its own 3 kW load.",
        day(SUMMER, 9),
        8,
        45,
        peak_kw=4.5,
        forecast=True,
        deembed=False,
    ),
]


def report():
    rows = {case.name: simulate(case) for case in CASES}
    return {
        "synthetic_only": True,
        "assumes_hypothetical_verified_executor": True,
        "physical_heater_operations": 0,
        "cloud_requests": 0,
        "assumptions": [
            "uniform 315 L tank, 0.3663 kWh/°C, full 3 kW element",
            "no hot-water draw-off or standing loss during the window",
            "Thermann cloud poll every 30 minutes, whole-degree readings (goal met within 0.5 °C)",
            "native Schedule heating not modelled (executor would replace it)",
            "default owner settings unless the case says otherwise",
        ],
        "rows": rows,
    }


def markdown(data):
    lines = [
        "# Closed-loop synthetic day scenarios",
        "",
        "Reproduce with `python tools/replay_shadow_days.py`. Each minute runs the real "
        "planner chain (forecast adapter → evaluate → cycle policy → decision) with a "
        "**hypothetical, verified** executor following the simulated cycle. No such executor "
        "exists and the heater is never operated. Assumptions: "
        + "; ".join(data["assumptions"])
        + ".",
        "",
        "| Scenario | Comfort met | Tank at end °C | First start | Cycles | kWh | Solar kWh | "
        "Cost AUD | All-grid AUD |",
        "|---|:-:|---:|:-:|---:|---:|---:|---:|---:|",
    ]
    for name, row in data["rows"].items():
        met = {True: "yes", False: "**NO**", None: "—"}[row["comfort_met"]]
        lines.append(
            f"| {name} | {met} | {row['final_tank_c']} | {row['first_start'] or '—'} | "
            f"{row['cycles']} | {row['energy_kwh']} | {row['solar_kwh']} | {row['cost_aud']} | "
            f"{row['same_energy_all_grid_aud']} |"
        )
    lines += ["", "## Decision sequences", ""]
    for name, row in data["rows"].items():
        sequence = " → ".join(f"{at} {code}" for at, code in row["decisions"])
        lines.append(f"- **{name}** — {row['description']} {sequence}")
    return "\n".join(lines) + "\n"


def main():
    data = report()
    (ROOT / "shadow_controller/DAY_SCENARIO_RESULTS.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    (ROOT / "shadow_controller/DAY_SCENARIO_RESULTS.md").write_text(
        markdown(data), encoding="utf-8"
    )
    print(markdown(data))


if __name__ == "__main__":
    main()
