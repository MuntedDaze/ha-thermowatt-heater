"""Reproducible offline cost/request comparisons, with explicit model limits.

Run: python tools/controller_replay.py --output docs/evidence/CONTROLLER_REPLAY.json
(0.18.0: the retired polling-day comparison moved to docs/history/smart-controller/.)
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
        for part in ("model", "config", "simple_policy", "adaptive")
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
                optional_session_active=state == sp.STORAGE and last is not None,
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
            dispatch_case(name, fn, minutes) for name, fn in cases.items() for minutes in (10, 5, 2)
        ],
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
