"""Deterministic four-state policy replay; no HA, network, MQTT or credentials.

Run python tools/dual_storage_replay.py --output docs/dual-storage/SIMULATION_RESULTS.json
Uses the production pure policy. Tank, forecasts and successful command/readback
latencies are synthetic; executor/bridge failure guards have separate regressions.
"""

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import json
from pathlib import Path

from controller_replay import modules


@dataclass(frozen=True)
class Case:
    name: str
    weather: str
    forecast: str
    weekend: bool = False
    draw_hour: float | None = None
    ct: bool = True
    initial_c: float = 45
    start_hour: int = 0


CASES = (
    Case("strong_sun_direct_70", "sun", "sun"),
    Case("cloudy_off_peak", "cloud", "cloud"),
    Case("patchy_optimistic_forecast", "patchy", "sun"),
    Case("patchy_pessimistic_forecast", "patchy", "cloud"),
    Case("unexpected_solar_after_normal", "late", "updates"),
    Case("unexpected_daytime_draw", "sun", "sun", draw_hour=14),
    Case("late_cold_start_before_peak", "sun", "sun", initial_c=30, start_hour=15),
    Case("weekend_surplus", "sun", "sun", weekend=True),
    Case("weekend_cloud", "cloud", "cloud", weekend=True),
    Case("ct_free_required_storage", "sun", "sun", ct=False),
    Case("forecast_sun_never_arrives", "cloud", "sun"),
)
STRATEGIES = ("previous_required_70", "required_62", "dual_62_optional_70")


def available(weather, hour):
    if weather == "sun":
        return 4.0 if 9.5 <= hour < 16 else 0.0
    if weather == "patchy":
        return (4.0 if int(hour * 60) % 60 < 35 else 0.0) if 10 <= hour < 16 else 0.0
    if weather in ("late", "early"):
        return 2.8 if 10 <= hour < 12.5 else 4.0 if weather == "late" and 13 <= hour < 16 else 0
    return 0.0


def replay(case, strategy):
    m, c, sp, _ = modules()
    settings, tariffs = c.parse_options({"tariff_clock": "standard"})
    s = replace(
        sp.PolicySettings(),
        normal_c=70 if strategy == STRATEGIES[0] else 62,
        boost_enabled=strategy == STRATEGIES[2],
        feed_in_rate=settings.feed_in_rate,
        tariff_clock="standard",
    )
    policy = sp.SimplePolicy(s, tariffs)
    date = 21 if case.weekend else 16
    start = datetime(2026, 11, date, case.start_hour, tzinfo=m.STANDARD).astimezone(m.UTC)
    minutes = (24 - case.start_hour) * 60
    temperature = case.initial_c
    physical = confirmed = sp.BASELINE
    last_command = pending = None
    reading, poll_at = temperature, start
    element = False
    solar_session = False
    latched = ended = None  # the executor's persisted weekend dates (local)
    commands, peak_observations = [], []
    buckets = {"peak_import": 0.0, "off_peak_import": 0.0, "solar": 0.0}
    costs = {"grid": 0.0, "feed_in_foregone": 0.0}
    requests = {k: 0 for k in ("status", "command_post", "auth_refresh")}
    token_at = last_status = None
    loss = draw_served = draw_unserved = forecast_error = max_temperature = 0.0

    def http(kind, minute):
        nonlocal token_at, last_status
        if token_at is None or minute - token_at >= 20:
            requests["auth_refresh"] += 1
            token_at = minute
        requests[kind] += 1
        if kind == "status":
            last_status = minute

    for i in range(minutes):
        now = start + timedelta(minutes=i)
        wall = now.astimezone(m.STANDARD)
        hour = wall.hour + wall.minute / 60
        tariff = m.tariff_at(now, tariffs, "standard")
        if pending is not None and i >= pending:
            http("status", i)
            confirmed, pending = physical, None
            reading, poll_at = round(temperature, 1), now
        if i % 30 == 0 and (last_status is None or i - last_status >= 3):
            http("status", i)
            reading, poll_at = round(temperature, 1), now
        surplus = available(case.weather, hour)
        heater_kw = s.element_kw if element else 0.0
        if case.ct:
            policy.add_meter(now, heater_kw - surplus, heater_kw=heater_kw)
        forecast_weather = (
            ("late" if hour >= 13.5 else "early") if case.forecast == "updates" else case.forecast
        )
        forecast = tuple(
            m.Forecast(
                now + timedelta(minutes=30 * j),
                now + timedelta(minutes=30 * (j + 1)),
                available(forecast_weather, hour + j / 2),
            )
            for j in range(18)
        )
        decision = policy.decide(
            sp.Snapshot(
                now,
                confirmed,
                reading,
                poll_at,
                forecast=forecast,
                last_command_at=last_command,
                heater_meter_valid=case.ct,
                optional_session_active=solar_session,
                measured_element_kw=heater_kw if case.ct and element else None,
                optional_allowed=len(commands)
                < int(c.DEFAULT_OPTIONS["controller_max_commands_per_day"]),
                cloud_ready=pending is None,
                # 0.17.0: the executor persists the weekend window per local day.
                weekend_latched=latched == now.astimezone(m.HOBART).date(),
                weekend_ended=ended == now.astimezone(m.HOBART).date(),
            )
        )
        if decision.plan.get("weekend_day_latched"):
            latched = now.astimezone(m.HOBART).date()
        if decision.plan.get("weekend_day_ended"):
            ended = now.astimezone(m.HOBART).date()
        if decision.command:
            # Synthetic success: POST now, exactly one confirmation a minute
            # later. No retry/401/lockout is assumed in this economic replay.
            http("status", i)
            http("command_post", i)
            physical, last_command, pending = decision.state, now, i + 1
            solar_session = decision.plan.get("heating_role") == "optional"
            commands.append(
                {
                    "at_aest": wall.isoformat(),
                    "state": physical,
                    "target_c": sp.TARGET_C.get(physical),
                    "reason": decision.reason,
                }
            )
        target = sp.TARGET_C.get(physical)
        if target is None:
            element = False
        elif temperature >= target:
            element = False
        elif temperature <= target - s.hysteresis_c:
            element = True
        # An already-running element continues inside the thermostat band.
        energy = s.element_kw / 60 if element else 0.0
        grid = max(0.0, energy - surplus / 60)
        solar = energy - grid
        buckets["peak_import" if tariff.kind == "peak" else "off_peak_import"] += grid
        buckets["solar"] += solar
        costs["grid"] += grid * tariff.rate
        costs["feed_in_foregone"] += solar * settings.feed_in_rate
        temperature += energy / s.kwh_per_c
        standing = 0.003 * max(0.0, temperature - 20) / 60
        temperature -= standing
        loss += standing * s.kwh_per_c
        # Identical specified useful energy demand, limited by actual modelled
        # stored energy above 15 C. Not a real shower-volume or hygiene model.
        demand = 2.5 if hour == 19 else 0.0
        if case.draw_hour is not None and hour == case.draw_hour:
            demand += 4.0
        served = min(demand, max(0, temperature - 15) * s.kwh_per_c)
        temperature -= served / s.kwh_per_c
        draw_served += served
        draw_unserved += demand - served
        max_temperature = max(max_temperature, temperature)
        forecast_error += abs(available(forecast_weather, hour) - surplus)
        if not case.weekend and wall.hour == 16 and wall.minute == 0:
            peak_observations.append(temperature)
    normal = s.normal_c if not case.weekend else s.baseline_c
    return {
        "scenario": case.name,
        "strategy": strategy,
        "ct_available": case.ct,
        "initial_c": case.initial_c,
        "simulated_hours": minutes / 60,
        "required_target_c": normal,
        "peak_import_kwh": buckets["peak_import"],
        "off_peak_import_kwh": buckets["off_peak_import"],
        "heater_solar_kwh": buckets["solar"],
        "lost_feed_in_aud": costs["feed_in_foregone"],
        "net_energy_cost_aud": sum(costs.values()),
        "standing_loss_kwh": loss,
        "useful_draw_kwh": draw_served,
        "unserved_draw_kwh": draw_unserved,
        "end_temperature_c": temperature,
        "end_stored_above_15_kwh": max(0, temperature - 15) * s.kwh_per_c,
        "maximum_temperature_c": max_temperature,
        "temperature_at_evening_peak_c": peak_observations[0] if peak_observations else None,
        "required_probe_target_reached_by_peak": (
            peak_observations[0] >= normal - 0.5 if peak_observations else None
        ),
        "storage_shortfall_at_peak_kwh": (
            max(0, normal - peak_observations[0]) * s.kwh_per_c if peak_observations else None
        ),
        "forecast_mae_kw": forecast_error / minutes,
        "commands": commands,
        "command_count": len(commands),
        "modelled_cloud_requests": requests,
        "modelled_cloud_request_count": sum(requests.values()),
    }


def results():
    _, c, _, _ = modules()
    _, tariffs = c.parse_options({"tariff_clock": "standard"})
    replacement_rate = min(t.rate for t in tariffs if t.kind == "off_peak")
    rows = []
    for case in CASES:
        group = [replay(case, strategy) for strategy in STRATEGIES]
        terminal = max(row["end_stored_above_15_kwh"] for row in group)
        for row in group:
            missing = terminal - row["end_stored_above_15_kwh"]
            row.update(
                common_terminal_stored_kwh=terminal,
                terminal_replenishment_kwh=missing,
                terminal_replenishment_aud=missing * replacement_rate,
                equal_service_terminal_cost_aud=row["net_energy_cost_aud"]
                + missing * replacement_rate,
            )
            rows.append(row)

    def rounded(value):
        if isinstance(value, float):
            return round(value, 6)
        if isinstance(value, dict):
            return {k: rounded(v) for k, v in value.items()}
        if isinstance(value, list):
            return [rounded(v) for v in value]
        return value

    return rounded(
        {
            "schema_version": 1,
            "cases": len(CASES),
            "strategies": list(STRATEGIES),
            "assumptions": {
                "tank": "315 L perfectly mixed; 3 kW; 8 C thermostat hysteresis; initial state Manual45",
                "loss": "0.3 percent of temperature difference above 20 C per hour",
                "tariff": "synthetic configured Aurora-like fixed AEST; not current price advice",
                "peak_policy": "Never schedule heating during peak, for every strategy",
                "cloud": "fixed 30-minute successful reads; 20-minute refresh heuristic; successful POST + 1-minute readback; counts are modelled, not measured",
                "service": "same 2.5 kWh useful evening draw; daytime-draw case adds 4 kWh; identical initial conditions per case",
                "equal_terminal": "hypothetical later off-peak grid replenishment to greatest terminal stored energy in each case; no extra loss/latency; not an executed plan",
                "replacement_aud_per_kwh": replacement_rate,
                "limits": "no stratification, native protective cycles, owner intervention, failed commands or outages; physical ON/OFF not verified by this model; target misses are explicit, not compensated by terminal value; no annual savings inference",
            },
            "rows": rows,
        }
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(results(), indent=2) + "\n", encoding="utf-8")
