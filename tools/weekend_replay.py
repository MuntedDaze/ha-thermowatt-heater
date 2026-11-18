"""Weekend comfort-window replays through the actual controller and bridge.

Synthetic only (offline HA/MQTT/cloud/tank harness). Each run simulates a full
week from Monday so command history and the weekday tariff are realistic, and
reports Saturday and Sunday: how and when the window opened, when 62/70 were
requested, the bottom reading at the 16:00 storage-ready time, the 18:00
return to baseline, commands per day and heater grid energy.

Not measured meteorology or household demand; not evidence of real savings.
"""

import argparse
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import socket
import tempfile

import final_week_replay as base
from morning_solar_delay_replay import MorningRun

m = base.m
SEASONS = {
    # name: (Monday date, sunrise, sunset local clock, clear-sky AC peak kW)
    "spring_nov": ((2026, 11, 16), 5.7, 20.6, 6.2),
    "summer_jan": ((2026, 1, 12), 5.9, 20.9, 6.5),
    "winter_jul": ((2026, 7, 13), 7.7, 16.8, 3.0),
}


class WeekendRun(MorningRun):
    def weather(self, local):
        local = local.astimezone(m.HOBART)
        sunrise, sunset, peak = SEASONS[self.scenario.get("season", "spring_nov")][1:]
        hour = local.hour + local.minute / 60
        if not sunrise <= hour <= sunset:
            return 0.0
        clear = peak * math.sin(math.pi * (hour - sunrise) / (sunset - sunrise))
        if local.weekday() >= 5 and self.scenario.get("weekend_cloud"):
            clear = min(clear, self.scenario["weekend_cloud"])
        return min(5.0, clear)

    def forecast_weather(self, local):
        return min(5.0, self.weather(local) * self.scenario.get("forecast_pv_factor", 1.0))

    def _forecast(self, pv=None):
        if self.scenario.get("missing_forecast") and self.now().astimezone(m.HOBART).weekday() >= 5:
            self.states.pop("sensor.emhass_pv", None)
            self.states.pop("sensor.emhass_load", None)
            return
        super()._forecast(pv)

    def _meter(self):
        super()._meter()
        local = self.now().astimezone(m.HOBART)
        stale = self.scenario.get("stale_pv_hours")
        if stale and local.weekday() == 5 and stale[0] <= local.hour < stale[1]:
            # The PV entity stops reporting: keep its last (pre-dawn) state.
            self.states[base.c.DEFAULT_SOURCES["pv"]] = self._frozen_pv
        else:
            self._frozen_pv = self.states[base.c.DEFAULT_SOURCES["pv"]]

    def demand(self, local):
        kwh = 2.5 if (local.hour, local.minute) in ((8, 0), (19, 0)) else 0.0
        if local.weekday() == 5 and (local.hour, local.minute) == (20, 0):
            kwh += 3.0  # Saturday evening bath
        return kwh

    def restart(self):
        from test_measured_performance import perf

        options = self.entry.options
        self.runtime = self.runtime_module.ShadowRuntime(
            self.hass, self.sources, *base.c.parse_options(options)
        )
        self.runtime.history = perf.MeasuredHistory.from_dict(self.store.get("week_history"))
        self.runtime.set_native_reference(options)
        self.executor = self._executor()
        self.install_history_store()

    def run_weekend(self):
        end = base.hobart(23, 0)  # Monday 00:00
        days = {}
        while self.now() < end:
            for _ in range(3):
                self.t += 20
                self.bridge.tick()
            self.tank.minute(self.t)
            local = self.now().astimezone(m.HOBART)
            served = min(self.demand(local), max(0, self.tank.t - 15) * m.TANK_KWH_PER_C)
            self.tank.t -= served / m.TANK_KWH_PER_C
            self._meter()
            if local.minute in (0, 30):
                self._forecast()
            if self.scenario.get("restart_at") == (local.weekday(), local.hour, local.minute):
                self.restart()
            self.runtime.update(self.now())
            drive = base.drive
            drive(self.runtime._save_history())
            drive(self.executor.async_step(self.now()))
            if local.weekday() < 5:
                continue
            day = days.setdefault(
                local.strftime("%a"),
                {
                    "window_opened": None,
                    "opened_by": None,
                    "first_62_request": None,
                    "first_70_request": None,
                    "reached_62": None,
                    "bottom_at_16_00": None,
                    "target_after_18_00": None,
                    "grid_heat_kwh": 0.0,
                    "solar_heat_kwh": 0.0,
                },
            )
            plan = self.executor.last_decision.plan
            if day["window_opened"] is None and plan.get("weekend_window_opened_by"):
                day["window_opened"] = local.strftime("%H:%M")
                day["opened_by"] = plan["weekend_window_opened_by"]
            if day["reached_62"] is None and self.tank.t >= 62:
                day["reached_62"] = local.strftime("%H:%M")
            if (local.hour, local.minute) == (16, 0):
                day["bottom_at_16_00"] = round(self.tank.t, 1)
            if (local.hour, local.minute) == (18, 10):
                day["target_after_18_00"] = (
                    self.tank.setpoint if self.tank.mode == "Manual" else "off"
                )
            if self.tank.element:
                pv = self.weather(local)
                solar = min(3.0, max(0.0, pv - 0.5))
                day["solar_heat_kwh"] += solar / 60
                day["grid_heat_kwh"] += (3.0 - solar) / 60
        for at, _endpoint, payload, _ in self.posts:
            local = at.astimezone(m.HOBART)
            if local.weekday() < 5:
                continue
            day = days[local.strftime("%a")]
            day.setdefault("posts", []).append(
                [
                    local.strftime("%H:%M"),
                    payload.get("T_SetPoint") if isinstance(payload, dict) else "off",
                ]
            )
            target = payload.get("T_SetPoint") if isinstance(payload, dict) else None
            key = {62: "first_62_request", 70: "first_70_request"}.get(target)
            if key and day[key] is None:
                day[key] = local.strftime("%H:%M")
        for day in days.values():
            day["commands"] = len(day.get("posts", []))
            day["grid_heat_kwh"] = round(day["grid_heat_kwh"], 2)
            day["solar_heat_kwh"] = round(day["solar_heat_kwh"], 2)
        return {
            "scenario": self.scenario["name"],
            "description": self.scenario["description"],
            "days": days,
        }


SCENARIOS = [
    {"name": "spring_clear", "description": "November clear weekend (AEDT)."},
    {
        "name": "summer_clear",
        "description": "January clear weekend (AEDT).",
        "season": "summer_jan",
    },
    {
        "name": "winter_clear",
        "description": "July clear weekend (AEST, 3 kW peak).",
        "season": "winter_jul",
    },
    {
        "name": "spring_cloudy",
        "description": "November weekend, PV never above 0.4 kW.",
        "weekend_cloud": 0.4,
    },
    {
        "name": "winter_cloudy",
        "description": "July weekend, PV never above 0.4 kW.",
        "season": "winter_jul",
        "weekend_cloud": 0.4,
    },
    {
        "name": "spring_partly_cloudy",
        "description": "November weekend, PV capped at 1.5 kW (window opens, no 70).",
        "weekend_cloud": 1.5,
    },
    {
        "name": "spring_missing_forecast",
        "description": "November clear weekend with no EMHASS forecast published.",
        "missing_forecast": True,
    },
    {
        "name": "spring_restart_in_window",
        "description": "November clear weekend; HA restarts Saturday 10:30.",
        "restart_at": (5, 10, 30),
    },
    {
        "name": "spring_stale_pv_meter",
        "description": "November clear weekend; PV entity stops reporting Saturday 05:00-10:00.",
        "stale_pv_hours": (5, 10),
    },
    {
        "name": "spring_pessimistic_forecast",
        "description": "November clear weekend; EMHASS PV forecast is 50% of actual.",
        "forecast_pv_factor": 0.5,
    },
]


def results(names=None):
    runs = []
    for scenario in SCENARIOS:
        if names and scenario["name"] not in names:
            continue
        date = SEASONS[scenario.get("season", "spring_nov")][0]
        start = datetime(*date, tzinfo=m.HOBART)
        with tempfile.TemporaryDirectory() as folder, base.pytest.MonkeyPatch.context() as patch:
            for name in ("connect", "connect_ex"):
                patch.setattr(socket.socket, name, base.denied)
            patch.setattr(socket, "getaddrinfo", base.denied)
            patch.setattr(socket, "create_connection", base.denied)
            patch.setattr(base.requests.Session, "request", base.denied)
            patch.setattr(base.bridge_module.MyThermowattBridge, "API_KEY", "SYNTHETIC_API_KEY")
            patch.setattr(base.bridge_module, "atomic_json", lambda path, data: None)
            # Shift the harness calendar (day 16 = this Monday), as the seasonal replay does.
            patch.setattr(
                base,
                "hobart",
                lambda d, h, minute=0, start=start: (
                    start + timedelta(days=d - 16, hours=h, minutes=minute)
                ).astimezone(m.UTC),
            )
            runs.append(WeekendRun(Path(folder), patch, scenario).run_weekend())
    return {
        "schema": 1,
        "synthetic": True,
        "note": "Synthetic replay through the real controller/bridge; not measured weather or demand.",
        "runs": runs,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", action="append")
    args = parser.parse_args()
    args.output.write_text(json.dumps(results(args.scenario), indent=2) + "\n", encoding="utf-8")
