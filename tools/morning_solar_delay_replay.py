"""Morning solar-boost delay scenarios through the actual controller and bridge.

Synthetic only: the same offline HA/MQTT/cloud/tank harness as the week
replays. No network, real account, Home Assistant installation or heater is
used. Each run simulates Monday 16 to Thursday 19 November 2026 (AEDT) so the
rolling 24-hour command history is realistic, then records every minute of
Thursday morning: measured export, qualification, the policy's boost reason,
the controller gate and the command that eventually starts 70 C.

This measures MECHANISMS. It does not reproduce, and cannot prove the cause
of, the owner's 19 November observation; that needs the live exports listed
in docs/solar-delay/INVESTIGATION.md.
"""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import socket
import tempfile

import final_week_replay as base
from next_major_replay import SmartWeek

m, c, hobart, drive = base.m, base.c, base.hobart, base.drive
THURSDAY = 19
EXPORT_W = base.c.DEFAULT_SOURCES["grid"]


class MorningRun(SmartWeek):
    """Sunny week, CT-free commissioned grid meter, Smart polling."""

    scenario: dict = {}

    def __init__(self, folder, monkeypatch, scenario):
        type(self).scenario = scenario
        super().__init__(folder, monkeypatch, scenario.get("polling", "smart"), False, False, 60)
        options = {
            **self.entry.options,
            "peak_heating_policy": scenario.get(
                "peak_policy", "Never schedule heating during peak"
            ),
            # Production forecast haircut and house margin (the base rig uses 0).
            "forecast_uncertainty": scenario.get("forecast_uncertainty", 0.25),
            "forecast_house_margin_kw": scenario.get("forecast_house_margin_kw", 0.3),
            "controller_max_commands_per_day": scenario.get("max_commands", 6),
            "heater_meter_verification": "",
        }
        self.entry.options.update(options)
        self.runtime.apply_options(self.entry.options, self.sources)
        self.runtime.set_native_reference(self.entry.options)
        self.executor.configure(self.entry.options)
        self.timeline = []
        self.blips = 0

    # --- synthetic site --------------------------------------------------------------------
    def weather(self, local):
        """Clear late-November Hobart day (AEDT), PV AC clipped at 5 kW."""
        local = local.astimezone(m.HOBART)
        hour = local.hour + local.minute / 60
        sunrise, sunset = 5.7, 20.6
        if not sunrise <= hour <= sunset:
            return 0.0
        clear = 6.2 * math.sin(math.pi * (hour - sunrise) / (sunset - sunrise))
        dip = self.scenario.get("cloud_dips")
        if dip and local.day == THURSDAY and 7 <= local.hour < 12 and local.minute % dip == 0:
            clear *= 0.45  # one minute of passing cloud
        if self.scenario.get("patchy_wednesday") and local.day == 18 and 11 <= local.hour < 16:
            clear *= 1 if (local.hour * 60 + local.minute) % 50 < 30 else 0.3
        return min(5.0, clear)

    def forecast_weather(self, local):
        factor = self.scenario.get("forecast_pv_factor", 1.0)
        return min(5.0, self.weather(local) * factor)

    def _forecast(self, pv=None):
        super()._forecast(pv)
        load = self.scenario.get("load_forecast_kw", 0.5)
        if load == "missing":
            self.states.pop("sensor.emhass_load", None)
            return
        for row in self.states["sensor.emhass_load"].attributes["forecasts"]:
            row["p_load_forecast"] = load

    def _meter(self):
        super()._meter()
        local = self.now().astimezone(m.HOBART)
        every = self.scenario.get("goodwe_unavailable_every")
        start, stop = self.scenario.get("goodwe_unavailable_hours", (6, 12))
        if (
            every
            and local.day == THURSDAY
            and start <= local.hour < stop
            and local.minute % every == 3
        ):
            # One evaluated report where the GoodWe integration is unavailable.
            self.report(EXPORT_W, "unavailable", {"unit_of_measurement": "W"})
            self.blips += 1

    def actions(self, local):
        return None

    def demand(self, local):
        """Showers 07:00 and 19:00, plus a larger Wednesday evening draw."""
        kwh = 2.5 if (local.hour, local.minute) in ((7, 0), (19, 0)) else 0.0
        if local.day == 18 and (local.hour, local.minute) == (20, 0):
            kwh += self.scenario.get("wednesday_extra_kwh", 2.0)
        return kwh

    # --- run -------------------------------------------------------------------------------
    def run_scenario(self):
        end = hobart(THURSDAY, 15, 0)
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
            self.runtime.update(self.now())
            drive(self.executor.async_step(self.now()))
            if local.day == THURSDAY and local.hour >= 5:
                self.record(local)
        return self.summary()

    def record(self, local):
        ex, ctl = self.executor, self.executor.controller
        plan = ex.last_decision.plan
        pv = self.weather(local)
        house = 0.5 + (3.0 if self.tank.element else 0.0)
        self.timeline.append(
            {
                "at": local.strftime("%H:%M"),
                "export_kw": round(pv - house, 2),
                "element": self.tank.element,
                "tank_c": round(self.tank.t, 1),
                "setpoint": self.tank.setpoint if self.tank.mode == "Manual" else self.tank.mode,
                "qualified": ex.policy.surplus_qualified(self.now()),
                "temperature_known": self.runtime.temperature_c is not None,
                "reason": ex.last_decision.reason,
                "boost_reason": plan.get("boost_reason"),
                "controller": ctl.reason,
                "commands_24h": len(ctl.commands),
            }
        )

    def summary(self):
        rows = self.timeline
        # The first minute an element-free 3.3 kW export was sustained 10 min
        # while the heater was not already at the boost target.
        first_qualified = next((r["at"] for r in rows if r["qualified"]), None)
        posts = [
            (at.astimezone(m.HOBART), payload)
            for at, endpoint, payload, _ in self.posts
            if at.astimezone(m.HOBART).day == THURSDAY
        ]
        first_70 = next(
            (
                at.strftime("%H:%M")
                for at, payload in posts
                if isinstance(payload, dict) and payload.get("T_SetPoint") == 70
            ),
            None,
        )
        blocking = Counter()
        for row in rows:
            if first_qualified and first_70 and first_qualified <= row["at"] < first_70:
                if row["qualified"]:
                    blocking[f"{row['boost_reason']} | {row['controller']}"] += 1
        not_boosting = Counter(
            row["boost_reason"] for row in rows if row["qualified"] and row["setpoint"] != 70
        )
        wednesday = [
            [
                at.astimezone(m.HOBART).strftime("%H:%M"),
                p.get("T_SetPoint") if isinstance(p, dict) else "off",
            ]
            for at, endpoint, p, _ in self.posts
            if at.astimezone(m.HOBART).day == 18
        ]
        return {
            "scenario": self.scenario["name"],
            "wednesday_posts": wednesday,
            "thursday_max_commands_24h": max((r["commands_24h"] for r in rows), default=None),
            "qualified_not_at_70_minutes_by_boost_reason": dict(not_boosting.most_common()),
            "description": self.scenario["description"],
            "first_qualified_export": first_qualified,
            "first_70_post": first_70,
            "delay_minutes": _minutes(first_qualified, first_70),
            "thursday_posts": [
                [
                    at.strftime("%H:%M"),
                    payload.get("T_SetPoint") if isinstance(payload, dict) else "off",
                ]
                for at, payload in posts
            ],
            "qualified_minutes_blocked_by": dict(blocking.most_common()),
            "goodwe_unavailable_reports": self.blips,
            "timeline": rows,
        }


def _minutes(a, b):
    if not a or not b:
        return None
    ha, ma = map(int, a.split(":"))
    hb, mb = map(int, b.split(":"))
    return (hb * 60 + mb) - (ha * 60 + ma)


SCENARIOS = [
    {
        "name": "clear_peak_never",
        "description": "Clear Thursday, CT-free grid meter, Smart polling, peak policy Never.",
    },
    {
        "name": "clear_peak_solar_only",
        "description": "As above with 'Verified solar-only heating' during peak.",
        "peak_policy": "Verified solar-only heating",
    },
    {
        "name": "goodwe_unavailable_every_7_min",
        "description": "Peak Never; one 'unavailable' GoodWe report every 7 min, 06:00-12:00.",
        "goodwe_unavailable_every": 7,
    },
    {
        "name": "passing_cloud_every_9_min",
        "description": "Peak Never; one minute of 45% PV every 9 min, 07:00-12:00.",
        "cloud_dips": 9,
    },
    {
        "name": "flat_household_load_1_2_kw",
        "description": "Peak Never; household forecast flat 1.2 kW instead of 0.5 kW.",
        "load_forecast_kw": 1.2,
    },
    {
        "name": "pessimistic_pv_forecast",
        "description": "Peak Never; EMHASS PV forecast 60% of the actual clear day.",
        "forecast_pv_factor": 0.6,
    },
    {
        "name": "goodwe_unavailable_during_session",
        "description": "Peak Never; one 'unavailable' GoodWe report every 7 min, 11:00-14:00.",
        "goodwe_unavailable_every": 7,
        "goodwe_unavailable_hours": (11, 14),
    },
    {
        "name": "patchy_wednesday_then_clear",
        "description": "Peak Never; Wednesday 11:00-16:00 alternates sun/cloud, Thursday clear.",
        "patchy_wednesday": True,
    },
    {
        "name": "patchy_wednesday_solar_only",
        "description": "Solar-only peak; patchy Wednesday, clear Thursday.",
        "patchy_wednesday": True,
        "peak_policy": "Verified solar-only heating",
    },
    {
        "name": "command_cap_8",
        "description": "Peak Never; rolling command cap 8 instead of 6.",
        "max_commands": 8,
    },
]


def results(names=None):
    rows = []
    for scenario in SCENARIOS:
        if names and scenario["name"] not in names:
            continue
        with tempfile.TemporaryDirectory() as folder, base.pytest.MonkeyPatch.context() as patch:
            for name in ("connect", "connect_ex"):
                patch.setattr(socket.socket, name, base.denied)
            patch.setattr(socket, "getaddrinfo", base.denied)
            patch.setattr(socket, "create_connection", base.denied)
            patch.setattr(base.requests.Session, "request", base.denied)
            patch.setattr(base.bridge_module.MyThermowattBridge, "API_KEY", "SYNTHETIC_API_KEY")
            journal = {}
            patch.setattr(
                base.bridge_module,
                "atomic_json",
                lambda path, data, journal=journal: journal.__setitem__(
                    str(path), json.loads(json.dumps(data))
                ),
            )
            rows.append(MorningRun(Path(folder), patch, scenario).run_scenario())
    return {
        "schema": 1,
        "synthetic": True,
        "note": "Mechanism replay only; not evidence of the cause of the 19 November observation.",
        "runs": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", action="append")
    parser.add_argument("--timeline", action="store_true", help="keep per-minute rows")
    args = parser.parse_args()
    data = results(args.scenario)
    if not args.timeline:
        for row in data["runs"]:
            row.pop("timeline")
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
