"""Synthetic minute traces; counterfactual full-power cycles, never HA or HTTP."""

from dataclasses import replace
from datetime import datetime, timedelta
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
package = ModuleType("_cycle_replay")
package.__path__ = [str(ROOT / "custom_components/thermann_shadow")]
sys.modules[package.__name__] = package
model = importlib.import_module(f"{package.__name__}.model")
config = importlib.import_module(f"{package.__name__}.config")
cycles = importlib.import_module(f"{package.__name__}.cycles")


def replay_case(cloud_minutes, peak=False, urgent=False, fast=False):
    settings, tariffs = config.parse_options({})
    if fast:
        # Deliberately naive benchmark, NOT an offered HA configuration.
        settings = replace(
            settings,
            solar_hold_minutes=0,
            solar_loss_minutes=0,
            minimum_cycle_minutes=0,
            minimum_gap_minutes=0,
            switching_benefit_aud=0.0001,
        )
    start = datetime(
        2026, 6, 9, 15 if peak else 11, 30 if peak else 0, tzinfo=model.HOBART
    ).astimezone(model.UTC)
    deadline = start + timedelta(hours=3 if urgent else 6)
    policy = cycles.CyclePolicy()
    for minute in range(int((deadline - start).total_seconds() / 60) + 1):
        now = start + timedelta(minutes=minute)
        loss_start = start + timedelta(minutes=40)
        loss_end = loss_start + timedelta(minutes=cloud_minutes)
        cloudy = loss_start <= now < loss_end
        # Published scenario forecast has a two-hour sun horizon. Unlike a real
        # forecast this synthetic benchmark knows the cloud duration; limitations
        # are explicit, with failed-forecast tests separately covering fallback.
        end = min(deadline, now + timedelta(hours=2))
        bounds = sorted({now, end, *[x for x in (loss_start, loss_end) if now < x < end]})
        future = tuple(
            model.Forecast(a, b, 0 if loss_start <= a < loss_end else 3.7)
            for a, b in zip(bounds, bounds[1:], strict=False)
        )
        plan = model.Plan(
            state="shadow_wait_for_window",
            net_export_kw=0 if cloudy else 4,
            deadline=deadline,
            mixed_model_energy_kwh=6.0,  # 120 ideal minutes at 3 kW
            modelled_heating_minutes=150,  # plus the 30-minute timing allowance
            latest_start=deadline - timedelta(minutes=120),
            grid_fallback_start=deadline - timedelta(minutes=120),
        )
        result = policy.step(now, plan, settings, tariffs, future, now)
        if result["state"] == "simulated_satisfied":
            break
    return {
        "cycles": policy.starts,
        "stops": policy.stops,
        "cost_aud": round(policy.cost, 4),
        "delivered_kwh": round(policy.delivered, 4),
        "shortfall_kwh": round(max(0, 6 - policy.delivered), 4),
        "suppressed_episodes": policy.suppressed_edges,
    }


def report():
    rows = []
    for peak, urgent, label in [
        (False, False, "off_peak"),
        (True, False, "peak_transition"),
        (False, True, "approaching_deadline"),
    ]:
        for duration in (2, 5, 10, 20, 30, 60):
            stable = replay_case(duration, peak, urgent)
            fast = replay_case(duration, peak, urgent, True)
            rows.append(
                {
                    "scenario": label,
                    "cloud_minutes": duration,
                    "stateful": stable,
                    "instantaneous_benchmark": fast,
                    "switch_events_avoided": fast["cycles"]
                    + fast["stops"]
                    - stable["cycles"]
                    - stable["stops"],
                    "cost_difference_aud_stateful_minus_benchmark": round(
                        stable["cost_aud"] - fast["cost_aud"], 4
                    ),
                }
            )
    return {
        "synthetic_only": True,
        "physical_heater_operations": 0,
        "cloud_requests": 0,
        "rows": rows,
    }


if __name__ == "__main__":
    print(json.dumps(report(), indent=2))
