"""Reproducible full-week real controller/bridge replay, synthetic I/O only.

Requires requirements-dev.txt. No HA installation, vendor or broker is contacted.
The test harness supplies a uniform tank and fake HA/MQTT/HTTP/atomic storage.
"""

import argparse
from collections import Counter
from datetime import timedelta
import json
import math
from pathlib import Path
import socket
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "thermowatt-heater"))

import pytest  # noqa: E402
import requests  # noqa: E402
from test_integration_0_9_0 import Rig, drive, hobart, m, c, SERIAL  # noqa: E402
from conftest import bridge_module  # noqa: E402


def denied(*args, **kwargs):
    raise AssertionError("Replay attempted external I/O")


class Week(Rig):
    def __init__(self, folder, monkeypatch, strategy, ct, event_aware=False, owner_minutes=60):
        self.strategy, self.ct = strategy, ct
        self.events, self.decisions = [], []
        self.poll_reasons = Counter()
        self.day_stats = {}
        self.owner_detection = None
        self.transient_detected = False
        self.owner_at = None
        self.original_owner_state = None
        self.status_max_age = self.unknown_minutes = 0
        self.healthy_status_max_age = 0
        self.critical_unknown_minutes = self.stale_command_blocks = 0
        self.forecast_abs = self.prediction_errors = 0.0
        self.prediction_n = 0
        self.prediction = None
        self.previous_cycle = False
        self.energy = {
            k: 0.0
            for k in (
                "peak",
                "off_peak",
                "solar",
                "grid_cost",
                "solar_opportunity",
                "served_draw",
                "unserved_draw",
                "loss",
                "peak_owner",
                "peak_unverified_lockout",
            )
        }
        super().__init__(
            folder,
            monkeypatch,
            hobart(16, 1),
            reading=45,
            pv=self.weather,
            mode="Manual",
            setpoint=45,
        )
        options = {
            **self.entry.options,
            "normal_storage_c": "62",
            "baseline_c": "45",
            "optional_solar_boost": True,
            "peak_heating_policy": "Never schedule heating during peak",
            "adaptive_polling_enabled": strategy == "actual_adaptive",
            "adaptive_polling_shadow": strategy == "previous_shadow",
            "event_aware_polling_enabled": event_aware,
            "owner_change_check_minutes": owner_minutes,
        }
        self.entry.options.update(options)
        if not ct:
            self.sources.pop("heater_power")
            options["heater_meter_verification"] = ""
        self.runtime.apply_options(options, self.sources)
        self.executor.configure(options)
        if strategy == "fixed_60":
            self.bridge.poll_interval = 3600
            self.bridge.next_poll = self.bridge.next_background[SERIAL] = self.bridge._next_slot()
            self.bridge.publish_diagnostics(force=True)
        if strategy == "actual_adaptive":
            self.bridge.options.update(
                adaptive_polling_enabled=True,
                adaptive_polling_qualified=True,
                event_aware_polling_qualified=event_aware,
            )
            self.bridge.poll_schedule.enabled = True
            self.bridge.poll_schedule.extended_qualified = event_aware
            self.bridge.poll_schedule.observed(
                SERIAL, self.bridge.last_success[SERIAL], self.bridge.poll_interval
            )
        self.install_history_store()
        self.enable()

    def install_history_store(self):
        rig = self

        class Store:
            async def async_save(self, data):
                rig.store["week_history"] = json.loads(json.dumps(data))

        self.runtime.history_store = Store()

    def weather(self, local):
        local = local.astimezone(m.STANDARD)
        hour = local.hour + local.minute / 60
        clear = 5 * max(0, math.sin(math.pi * (hour - 6) / 12))
        if local.weekday() in (1, 6):
            return clear * 0.08
        if local.weekday() == 2:
            return clear * (1 if local.minute % 25 < 12 else 0.08)
        return clear

    def forecast_weather(self, local):
        local = local.astimezone(m.STANDARD)
        hour = local.hour + local.minute / 60
        # Tuesday and Wednesday have deliberately optimistic forecasts.
        return 5 * max(0, math.sin(math.pi * (hour - 6) / 12))

    def _forecast(self, pv=None):
        super()._forecast(pv or self.forecast_weather)

    def cloud(self, method, url, **kwargs):
        local = self.now().astimezone(m.STANDARD)
        if (
            url.endswith("/status")
            and local.weekday() == 4
            and (local.hour == 15 and local.minute >= 30 or local.hour == 16 and local.minute < 30)
        ):
            raise requests.Timeout("SYNTHETIC_STATUS_OUTAGE")
        result = super().cloud(method, url, **kwargs)
        if (
            url.endswith("/status")
            and local.weekday() == 2
            and local.hour == 12
            and 3 <= local.minute <= 8
        ):
            self.transient_detected = self.tank.reported[1] == 55
        return result

    def event(self, name):
        self.events.append({"at": self.now().isoformat(), "event": name})

    def actions(self, local):
        if local.weekday() == 2:
            if (local.hour, local.minute) == (12, 3):
                self.original_owner_state = (self.tank.mode, self.tank.setpoint)
                self.tank.apply("Manual", 55, self.t)
                self.event("transient_app_change")
            elif (local.hour, local.minute) == (12, 8):
                self.tank.apply(*self.original_owner_state, self.t)
                self.event("transient_app_return")
            elif (local.hour, local.minute) == (
                12,
                20,
            ) and self.executor.controller.state == "owner_override":
                drive(self.executor.async_owner_action("resume"))
                self.event("owner_resumes_after_transient")
            elif (local.hour, local.minute) == (17, 15):
                self.tank.apply("Manual", 55, self.t)
                self.owner_at = self.now()
                self.event("persistent_owner_app_change")
            elif (local.hour, local.minute) == (19, 15):
                self.tank.apply("Off", 55, self.t)
                drive(self.executor.async_owner_action("resume"))
                self.event("owner_returns_off_and_resumes")
        if local.weekday() == 5 and (local.hour, local.minute) == (6, 30):
            from test_measured_performance import perf

            options = self.entry.options
            self.runtime = self.runtime_module.ShadowRuntime(
                self.hass, self.sources, *c.parse_options(options)
            )
            self.runtime.history = perf.MeasuredHistory.from_dict(self.store.get("week_history"))
            self.runtime.set_native_reference(options)
            self.executor = self._executor()
            self.install_history_store()
            self.event("HA_controller_and_history_restart_no_intent_replay")
        if (
            local.weekday() == 5
            and (local.hour, local.minute) == (9, 0)
            and self.executor.controller.state == "fault_locked"
        ):
            drive(self.executor.async_owner_action("acknowledge"))
            self.event("owner_acknowledges_recovered_fault")

    def run_week(self):
        end = hobart(23, 1)  # 00:00 AEST Monday to 00:00 AEST following Monday
        previous_reason = None
        while self.now() < end:
            for _ in range(3):
                self.t += 20
                self.bridge.tick()  # genuine backoff; no test override of next_cloud
            self.tank.minute(self.t)
            local = self.now().astimezone(m.STANDARD)
            accounting_local = local if self.now() < end else local - timedelta(seconds=1)
            key = accounting_local.date().isoformat()
            day = self.day_stats.setdefault(
                key,
                {
                    "required_c": 62 if accounting_local.weekday() < 5 else None,
                    "max_daytime_c": 0.0,
                    "at_peak_c": None,
                },
            )
            if 9 <= local.hour < 16:
                day["max_daytime_c"] = max(day["max_daytime_c"], self.tank.t)
            if (local.hour, local.minute) == (16, 0):
                day["at_peak_c"] = self.tank.t
            self.actions(local)
            demand = 2.5 if (local.hour, local.minute) in ((7, 0), (19, 0)) else 0
            if local.weekday() == 3 and (local.hour, local.minute) == (13, 0):
                demand += 4
            if local.weekday() == 4 and (local.hour, local.minute) == (15, 20):
                demand += 6
            served = min(demand, max(0, self.tank.t - 15) * m.TANK_KWH_PER_C)
            self.tank.t -= served / m.TANK_KWH_PER_C
            self.energy["served_draw"] += served
            self.energy["unserved_draw"] += demand - served
            self.energy["loss"] += 0.2 / 60 * m.TANK_KWH_PER_C
            self._meter()
            outage = (
                local.weekday() == 4
                and 11 * 60 + 20 <= local.hour * 60 + local.minute < 12 * 60 + 20
            )
            if self.ct and not outage:
                self.report(
                    "sensor.synthetic_heater_w",
                    3000 if self.tank.element else 0,
                    {"unit_of_measurement": "W"},
                )
            if local.minute in (0, 30):
                self._forecast()
            self.runtime.update(self.now())
            drive(self.runtime._save_history())
            drive(self.executor.async_step(self.now()))
            if (
                self.executor.last_decision.plan.get("mode") == "deadline"
                and self.runtime.temperature_c is None
            ):
                self.critical_unknown_minutes += 1
            self.stale_command_blocks += (
                "heater_status_too_old" in self.executor.controller.gate_failures
            )
            watts = 3 if self.tank.element else 0
            pv = self.weather(self.now())
            imported = min(watts, max(0, watts + 0.5 - pv)) / 60
            solar = watts / 60 - imported
            tariff = m.tariff_at(self.now(), self.runtime.tariffs, "standard")
            self.energy["peak" if tariff.kind == "peak" else "off_peak"] += imported
            if tariff.kind == "peak":
                owner_period = (
                    local.weekday() == 2
                    and 17 * 60 + 15 <= local.hour * 60 + local.minute < 19 * 60 + 15
                )
                self.energy["peak_owner" if owner_period else "peak_unverified_lockout"] += imported
            self.energy["solar"] += solar
            self.energy["grid_cost"] += imported * tariff.rate
            self.energy["solar_opportunity"] += solar * self.runtime.settings.feed_in_rate
            age = max(0, self.t - self.bridge.last_success.get(SERIAL, self.t)) / 60
            self.status_max_age = max(self.status_max_age, age)
            if self.bridge.cloud_health == "ok":
                self.healthy_status_max_age = max(self.healthy_status_max_age, age)
            self.unknown_minutes += self.runtime.temperature_c is None
            self.forecast_abs += abs(self.forecast_weather(self.now()) - pv)
            self.poll_reasons[self.bridge.poll_schedule.summary(SERIAL)["reason"]] += 1
            if (
                self.owner_at is not None
                and self.owner_detection is None
                and self.executor.controller.state == "owner_override"
            ):
                self.owner_detection = (self.now() - self.owner_at).total_seconds() / 60
            reason = self.executor.controller.reason
            if reason != previous_reason:
                self.decisions.append(
                    {
                        "at": self.now().isoformat(),
                        "reason": reason,
                        "state": self.executor.controller.state,
                        "target_c": self.tank.setpoint,
                    }
                )
                previous_reason = reason
            if (
                demand
                or outage
                or self.tank.mode != "Manual"
                or not self.runtime.circuit.valid
                or (self.prediction and self.prediction[1] != self.tank.setpoint)
                or (not self.tank.element and self.tank.t < self.tank.setpoint)
            ):
                self.prediction = None
            if (
                self.ct
                and self.tank.element
                and self.prediction is None
                and self.runtime.completion.get("latest")
            ):
                from datetime import datetime

                self.prediction = (
                    datetime.fromisoformat(self.runtime.completion["latest"]),
                    self.tank.setpoint,
                )
            if self.prediction and self.tank.t >= self.prediction[1]:
                self.prediction_errors += (
                    abs((self.now() - self.prediction[0]).total_seconds()) / 60
                )
                self.prediction_n += 1
                self.prediction = None
        for day in self.day_stats.values():
            day["required_target_reached"] = (
                day["max_daytime_c"] >= day["required_c"] - 0.5 if day["required_c"] else None
            )
            day["at_peak_storage_shortfall_kwh"] = (
                max(0, day["required_c"] - day["at_peak_c"]) * m.TANK_KWH_PER_C
                if day["required_c"] and day["at_peak_c"] is not None
                else None
            )
        return {
            "strategy": self.strategy,
            "ct": self.ct,
            "energy_kwh": {
                k: v for k, v in self.energy.items() if k not in ("grid_cost", "solar_opportunity")
            },
            "grid_cost_aud": self.energy["grid_cost"],
            "solar_opportunity_aud": self.energy["solar_opportunity"],
            "net_heater_cost_aud": self.energy["grid_cost"] + self.energy["solar_opportunity"],
            "end_temperature_c": self.tank.t,
            "end_stored_above_15_kwh": max(0, self.tank.t - 15) * m.TANK_KWH_PER_C,
            "command_intents": len(self.commands()),
            "command_posts": len(self.posts),
            "http_categories": dict(self.bridge.usage.counts),
            "http_total": self.bridge.usage.total,
            "maximum_status_age_minutes": self.status_max_age,
            "maximum_healthy_status_age_minutes": self.healthy_status_max_age,
            "unknown_temperature_minutes": self.unknown_minutes,
            "required_planning_unknown_minutes": self.critical_unknown_minutes,
            "stale_command_blocked_minutes": self.stale_command_blocks,
            "persistent_owner_detection_minutes": self.owner_detection,
            "transient_app_change_observed": self.transient_detected,
            "forecast_mae_kw": self.forecast_abs / (7 * 1440),
            "conditional_latest_completion_mae_minutes": self.prediction_errors / self.prediction_n
            if self.prediction_n
            else None,
            "evaluated_completion_samples": self.prediction_n,
            "shadow_would_reads": self.executor.poll_shadow.would_polls,
            "poll_reason_minutes": dict(self.poll_reasons),
            "days": self.day_stats,
            "events": self.events,
            "decisions": self.decisions,
            "notifications": sorted(set(self.notifications)),
            "clean_history_sessions": len(self.runtime.history.sessions),
        }


def results(strategies=None):
    strategies = strategies or [
        (name, name, False, 60)
        for name in ("fixed_30", "fixed_60", "previous_shadow", "actual_adaptive")
    ]
    rows = []
    for ct in (False, True):
        for label, strategy, event_aware, owner_minutes in strategies:
            with tempfile.TemporaryDirectory() as folder, pytest.MonkeyPatch.context() as patch:
                patch.setattr(socket.socket, "connect", denied)
                patch.setattr(socket.socket, "connect_ex", denied)
                patch.setattr(socket, "getaddrinfo", denied)
                patch.setattr(socket, "create_connection", denied)
                patch.setattr(requests.Session, "request", denied)
                patch.setattr(bridge_module.MyThermowattBridge, "API_KEY", "SYNTHETIC_API_KEY")
                journal = {}
                patch.setattr(
                    bridge_module,
                    "atomic_json",
                    lambda path, data, journal=journal: journal.__setitem__(
                        str(path), json.loads(json.dumps(data))
                    ),
                )
                row = Week(Path(folder), patch, strategy, ct, event_aware, owner_minutes).run_week()
                row["strategy"] = label
                rows.append(row)
        group = rows[-len(strategies) :]
        terminal = max(r["end_stored_above_15_kwh"] for r in group)
        for row in group:
            missing = terminal - row["end_stored_above_15_kwh"]
            row.update(
                common_terminal_stored_kwh=terminal,
                terminal_replenishment_kwh=missing,
                equal_terminal_cost_aud=row["net_heater_cost_aud"] + missing * 0.1702,
            )

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
            "simulated_days_per_run": 7,
            "runs": rows,
            "assumptions": {
                "tank": "315 L uniform / 3 kW / native 8 C hysteresis / 0.2 C per hour loss; receipt-rounded cloud probe; native protective cycles omitted",
                "service": "identical 2.5 kWh morning + evening demand; Thursday adds 4 and Friday 6; initial45, equal terminal replenishment hypothetical later grid at0.1702",
                "weather": "Mon sunny, Tue cloudy with optimistic forecast, Wed patchy, Thu heavy draw, Fri CT and cloud-status outages, Sat restart, Sun cloudy weekend",
                "owner": "Wednesday five-minute app change and later two-hour Manual55 peak intervention; simulated owner resumes explicitly, never auto-overwrites owner hold",
                "cloud": "actual mocked worker, 30s command readback, existing 20m refresh heuristic, authentic backoff; atomic private storage simulated in memory to avoid platform filesystem noise",
                "old_shadow": "previous_shadow leaves actual fixed30 unchanged; shadow_would_reads is advisory on actual observations, not a closed-loop estimate of HTTP or energy savings",
                "cost": "marginal heater grid + foregone feed-in; no whole-house bill or annual savings claim; zero OFF watts only a tank-model assumption",
                "prediction": "conditional latest bound error against simulated target crossing; sparse/changed/drawn cycles excluded, not real measured hardware accuracy",
            },
        }
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(results(), indent=2) + "\n", encoding="utf-8")
