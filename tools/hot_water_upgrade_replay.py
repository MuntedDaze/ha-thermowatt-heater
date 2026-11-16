"""Four hot-water strategies through the actual executor/bridge; synthetic I/O only."""

import argparse
import json
import math
from pathlib import Path
import socket
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import pytest  # noqa: E402
import requests  # noqa: E402
from test_existing_installation_upgrade import ct_free  # noqa: E402
from test_integration_0_9_0 import Rig, c, hobart, m  # noqa: E402

STRATEGIES = ("required_only", "off_peak_solar", "ct_free_all_solar", "verified_ct_all_solar")
SCENARIOS = ("clear", "passing_cloud", "sustained_cloud", "appliance", "shower", "weekend")


def denied(*args, **kwargs):
    raise AssertionError("External I/O prohibited in replay")


def run_case(folder, monkeypatch, strategy, scenario):
    folder.mkdir(parents=True, exist_ok=True)
    day = 14 if scenario == "weekend" else 16

    def weather(loc):
        hour = loc.hour + loc.minute / 60
        pv = min(5, max(0, 5.5 * math.sin(math.pi * (hour - 6) / 14)))
        minute = loc.hour * 60 + loc.minute
        if scenario == "passing_cloud" and 10 * 60 + 10 <= minute < 10 * 60 + 14:
            return 0.3
        if scenario == "sustained_cloud" and 10 * 60 + 10 <= minute < 10 * 60 + 50:
            return 0.3
        return pv

    rig = Rig(
        folder, monkeypatch, hobart(day, 0, 10), reading=46, mode="Manual", setpoint=45, pv=weather
    )
    if strategy != "verified_ct_all_solar":
        ct_free(rig)
    rig.entry.options.update(
        normal_storage_c="62",
        optional_solar_boost=strategy != "required_only",
        peak_heating_policy="Verified solar-only heating"
        if strategy in {"ct_free_all_solar", "verified_ct_all_solar"}
        else "Never schedule heating during peak",
    )
    rig.runtime.apply_options(rig.entry.options, rig.sources)
    rig.executor.configure(rig.entry.options)
    totals = {
        k: 0.0
        for k in (
            "solar_kwh",
            "peak_import_kwh",
            "off_peak_import_kwh",
            "grid_cost_aud",
            "foregone_export_aud",
            "heat_kwh",
            "draw_kwh",
        )
    }
    max_exit = 0
    maximum = 0
    peak_temperature = None
    morning = None

    def meter():
        loc = rig.now().astimezone(m.HOBART)
        base = 0.5 + (
            2.8 if scenario == "appliance" and loc.hour == 10 and 10 <= loc.minute < 30 else 0
        )
        generation = weather(loc)
        house = base + (3 if rig.tank.element else 0)
        for key, value in (("grid", generation - house), ("house", house), ("pv", generation)):
            rig.report(c.DEFAULT_SOURCES[key], value * 1000, {"unit_of_measurement": "W"})
        rig.report(c.DEFAULT_PV_AC, generation * 1000, {"unit_of_measurement": "W"})

    rig._meter = meter
    rig.enable()

    def observe(r):
        nonlocal max_exit, maximum, peak_temperature, morning
        loc = r.now().astimezone(m.HOBART)
        if scenario == "shower" and (loc.hour, loc.minute) == (10, 15):
            draw = min(3.0, max(0, r.tank.t - 15) * m.TANK_KWH_PER_C)
            r.tank.t -= draw / m.TANK_KWH_PER_C
            totals["draw_kwh"] += draw
        heater = 3 if r.tank.element else 0
        base = 0.5 + (
            2.8 if scenario == "appliance" and loc.hour == 10 and 10 <= loc.minute < 30 else 0
        )
        imported = min(heater, max(0, base + heater - weather(loc))) / 60
        solar = heater / 60 - imported
        tariff = m.tariff_at(r.now(), TARIFFS, "standard")
        totals["peak_import_kwh" if tariff.kind == "peak" else "off_peak_import_kwh"] += imported
        totals["solar_kwh"] += solar
        totals["heat_kwh"] += heater / 60
        totals["grid_cost_aud"] += imported * tariff.rate
        totals["foregone_export_aud"] += solar * 0.09276
        maximum = max(maximum, r.tank.t) if 11 <= loc.hour < 17 else maximum
        if (loc.hour, loc.minute) == (17, 0):
            peak_temperature = r.tank.t
        if (loc.hour, loc.minute) == (7, 0):
            morning = r.tank.t
        max_exit = max(
            max_exit, r.executor.controller.summary(r.now())["protective_exit_wait_seconds"]
        )

    _, TARIFFS = c.parse_options({"tariff_clock": "standard"})
    rig.run(hobart(day + 1, 0, 10), observe)
    target_miss = scenario != "weekend" and maximum < 61.5
    # Equal terminal energy, replenished hypothetically off-peak at model rates.
    replenishment = max(0, 70 - rig.tank.t) * m.TANK_KWH_PER_C
    result = {
        "strategy": strategy,
        "scenario": scenario,
        **{k: round(v, 6) for k, v in totals.items()},
        "end_temperature_c": round(rig.tank.t, 3),
        "normal_target_missed": target_miss,
        "probe_at_peak_c": round(peak_temperature, 3) if peak_temperature is not None else None,
        "morning_probe_c": round(morning, 3) if morning is not None else None,
        "http": dict(rig.bridge.usage.counts),
        "http_total": rig.bridge.usage.total,
        "command_posts": len(rig.posts),
        "optional_start_intents": sum(
            x.get("reason")
            in {
                "peak_solar_qualified",
                "solar_opportunity",
                "weekday_solar_boost",
                "weekday_direct_solar_boost",
            }
            for x in rig.executor.controller.history
        ),
        "longest_unresolved_exit_seconds": max_exit,
        "terminal_replenishment_kwh": round(replenishment, 6),
        "equal_terminal_heat_cost_aud": round(
            totals["grid_cost_aud"] + totals["foregone_export_aud"] + replenishment * 0.1702, 6
        ),
        "confirmation_failures": sum(
            x.get("status") != "confirmed" for x in rig.executor.controller.history
        ),
    }
    return result


def results():
    rows = []
    with tempfile.TemporaryDirectory(prefix="thermann-offline-replay-") as folder:
        for scenario in SCENARIOS:
            for strategy in STRATEGIES:
                with pytest.MonkeyPatch.context() as monkeypatch:
                    for target in (
                        "socket.create_connection",
                        "socket.getaddrinfo",
                        "requests.Session.request",
                    ):
                        monkeypatch.setattr(target, denied)
                    monkeypatch.setattr(socket.socket, "connect", denied)
                    monkeypatch.setattr(socket.socket, "connect_ex", denied)
                    monkeypatch.setattr(requests, "request", denied)
                    rows.append(
                        run_case(
                            Path(folder) / f"{scenario}-{strategy}", monkeypatch, strategy, scenario
                        )
                    )
    return {
        "schema_version": 1,
        "synthetic": True,
        "runs": rows,
        "assumptions": "Uniform315L/3kW tank,8C thermostat hysteresis,0.2C/h loss; actual production policy/executor/bridge with mocked HTTP/MQTT,30s cloud readback and existing auth budgets. Equal terminal70C replenished hypothetically off-peak; no annual or measured household savings claim. Actual net house import can exceed attributable heater import. Outage/restart/auth/session failures are covered by the separate full-week and fault regressions.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(results(), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
