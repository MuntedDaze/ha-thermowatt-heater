"""Reproducible offline cost/request comparisons, with explicit model limits.

Run: python tools/controller_replay.py --output docs/smart-controller/SIMULATION_RESULTS.json
No HA installation, network, credentials, MQTT or device access.
"""

import argparse
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType


def modules():
    name = "_controller_replay"
    if name not in sys.modules:
        package = ModuleType(name)
        package.__path__ = [
            str(Path(__file__).resolve().parents[1] / "custom_components/thermann_shadow")
        ]
        sys.modules[name] = package
    return tuple(
        importlib.import_module(f"{name}.{part}")
        for part in ("model", "config", "simple_policy", "polling")
    )


def dispatch_case(name, availability, withdrawal=5, later_solar=False):
    m, c, sp, _ = modules()
    settings, tariffs = c.parse_options({"tariff_clock": "standard"})
    s = replace(
        sp.PolicySettings(normal_c=70, peak_policy=sp.PEAK_SOLAR),
        withdraw=timedelta(minutes=withdrawal),
    )
    policy = sp.SimplePolicy(s, tariffs)
    start = datetime(2026, 11, 16, 9, tzinfo=m.HOBART).astimezone(timezone.utc)
    state, last = sp.OFF, None
    imported = solar = energy = 0.0
    commands = []
    for i in range(30):
        now = start + timedelta(minutes=i)
        available = availability(i)
        heater = 3 if state == sp.STORAGE else 0
        policy.add_meter(now, heater - available, heater_kw=heater)
        decision = policy.decide(
            sp.Snapshot(
                now,
                state,
                45,
                now,
                forecast=(m.Forecast(start, start + timedelta(hours=2), 3.5),),
                last_command_at=last,
                heater_meter_valid=True,
            )
        )
        if decision.command:
            state, last = decision.state, now
            commands.append({"minute": i, "state": state, "reason": decision.reason})
        heater = 3 if state == sp.STORAGE else 0
        grid = min(heater, max(0, heater - available))
        imported += grid / 60
        solar += (heater - grid) / 60
        energy += heater / 60
    remaining = max(0, 1.5 - energy)  # equal useful heat delivered in the later opportunity
    later_grid = 0 if later_solar else remaining
    solar += remaining if later_solar else 0
    peak = m.tariff_at(start, tariffs, "standard").rate
    off = min(t.rate for t in tariffs if t.kind == "off_peak")
    return {
        "scenario": name,
        "withdraw_minutes": withdrawal,
        "peak_import_kwh": round(imported, 6),
        "off_peak_import_kwh": round(later_grid, 6),
        "heater_solar_kwh": round(solar, 6),
        "export_lost_kwh": round(solar, 6),
        "lost_feed_in_aud": round(solar * settings.feed_in_rate, 6),
        "net_heat_cost_aud": round(
            imported * peak + later_grid * off + solar * settings.feed_in_rate, 6
        ),
        "useful_heat_kwh": round(energy + remaining, 6),
        "equal_service_achieved": energy + remaining >= 1.5 - 1e-9,
        "forecast_error_mae_kw": round(sum(abs(3.5 - availability(i)) for i in range(30)) / 30, 6),
        "commands": commands,
        "command_count": len(commands),
        "estimated_incremental_command_http": 3 * len(commands),
        "limits": "30-minute pure policy dispatch; later replenishment guaranteed; no tank stratification or command latency",
    }


def polling_day(strategy):
    _, _, _, p = modules()
    start = datetime(2026, 11, 16, tzinfo=timezone.utc)
    shadow = p.PollingShadow(True)
    counts = {
        kind: 0
        for kind in (
            "auth_refresh",
            "routine_status",
            "pre_command_status",
            "command_post",
            "confirmation_status",
        )
    }
    status_minutes = []
    token_at = None
    last_status = None
    last_command = None
    commands = {367, 667, 907, 1327}

    def request(kind, minute):
        nonlocal token_at, last_status
        if token_at is None or minute - token_at >= 20:
            counts["auth_refresh"] += 1
            token_at = minute
        counts[kind] += 1
        if kind != "command_post":
            last_status = minute
            status_minutes.append(minute)

    for i in range(1440):
        if i in commands:
            if last_status is None or i - last_status > 1:
                request("pre_command_status", i)
            request("command_post", i)
            last_command = i
        if i - 1 in commands:
            request("confirmation_status", i)
        if strategy == "adaptive":
            due = shadow.observe(
                p.PollContext(
                    start + timedelta(minutes=i),
                    start + timedelta(minutes=last_status) if last_status is not None else None,
                    any(a <= i < b for a, b in ((367, 607), (667, 807), (907, 1027))),
                    command_at=start + timedelta(minutes=last_command)
                    if last_command is not None
                    else None,
                )
            )
            due = due or i == 0
        else:
            due = i % int(strategy) == 0
        if due and (last_status is None or i - last_status > 3):
            request("routine_status", i)
    owner_event = 383
    detection = next((i - owner_event for i in status_minutes if i >= owner_event), None)
    return {
        "strategy": strategy,
        "http": counts,
        "total_http": sum(counts.values()),
        "persistent_owner_event_detection_minutes": detection,
        "transient_event_384_to_393_missed": not any(384 <= i <= 393 for i in status_minutes),
        "maximum_status_gap_minutes": max(
            b - a for a, b in zip(status_minutes, status_minutes[1:], strict=False)
        ),
        "limits": "synthetic fixed command timeline; 20-minute refresh heuristic; successful reads only; no vendor expiry assertion",
    }


def report():
    cases = {
        "clear": lambda i: 3.5,
        "short_sun_then_dark": lambda i: 3.5 if i < 13 else 0,
        "four_minute_cloud": lambda i: 0 if 14 <= i < 18 else 3.5,
        "small_import": lambda i: 2.85 if i >= 11 else 3.5,
    }
    return {
        "schema_version": 1,
        "evidence": "synthetic offline comparisons, not observed outcomes or savings promises",
        "operating_policy": "Manual 45 baseline, weekday Manual 70 retained; native protections unchanged",
        "dispatch": [
            dispatch_case(name, fn, minutes) for name, fn in cases.items() for minutes in (5, 2)
        ],
        "polling": [polling_day(strategy) for strategy in ("30", "60", "adaptive")],
        "full_controller_evidence": "tests/test_integration_0_9_0.py and tests/test_audit_regressions_0_9_1.py exercise real executor/bridge with synthetic cloud",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(report(), indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(result, encoding="utf-8")
    else:
        print(result, end="")
