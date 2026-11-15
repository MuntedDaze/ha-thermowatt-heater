"""Compact measured-energy history and cautious bottom-sensor calibration.

No cloud reads or commands. HA Recorder owns the raw timeline. Power integration
never bridges a missing report or restart. Learned slopes are diagnostics until
independent validation; a single probe cannot establish whole-tank heat/comfort.
"""

from collections import deque
from datetime import datetime, timedelta
import math
from statistics import median

from .model import UTC

# Three target cohorts each need >=20 sessions plus held-out coverage. The old
# 40-row total could never retain enough evidence for all three at once.
MAX_SESSIONS = 120
SAVE_INTERVAL = timedelta(minutes=15)


def _at(value):
    try:
        result = datetime.fromisoformat(value)
        return result.astimezone(UTC) if result.tzinfo else None
    except (ValueError, TypeError):
        return None


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


class MeasuredHistory:
    def __init__(self, tank_litres=315.0, nominal_kw=3.0):
        self.tank_litres, self.nominal_kw = tank_litres, nominal_kw
        self.integrated_kwh = 0.0
        self.covered_seconds = 0.0
        self.gaps = 0
        self.counter_epochs = 0
        self.counter_delta_kwh = 0.0
        self.counter = None
        self.sessions = deque(maxlen=MAX_SESSIONS)
        self.last = None  # deliberately not restored: no power extrapolation over restart
        self.anchor = None
        self.candidate = None
        self.dirty = False
        self._saved_at = None
        self._saved_sessions = 0
        self.meter_identity = ""
        self.cycle = None

    @property
    def physics(self):
        return self.tank_litres * 4.186 / 3600

    def configure(self, tank_litres, nominal_kw, identity=None):
        identity = self.meter_identity if identity is None else identity
        if (tank_litres, nominal_kw, identity) != (
            self.tank_litres,
            self.nominal_kw,
            self.meter_identity,
        ):
            self.last = self.anchor = self.candidate = None
            self.dirty = True
            self.cycle = None
        self.tank_litres, self.nominal_kw = tank_litres, nominal_kw
        self.meter_identity = identity

    def to_dict(self):
        return {
            "version": 2,
            "tank_litres": self.tank_litres,
            "nominal_kw": self.nominal_kw,
            "meter_identity": self.meter_identity,
            "integrated_kwh": self.integrated_kwh,
            "covered_seconds": self.covered_seconds,
            "gaps": self.gaps,
            "counter_epochs": self.counter_epochs,
            "counter_delta_kwh": self.counter_delta_kwh,
            "counter": self.counter,
            "sessions": list(self.sessions),
        }

    @classmethod
    def from_dict(cls, data):
        obj = cls()
        if not isinstance(data, dict) or data.get("version") not in (1, 2):
            return obj
        if (
            data["version"] == 2
            and _finite(data.get("tank_litres"))
            and _finite(data.get("nominal_kw"))
            and 50 <= data["tank_litres"] <= 500
            and 2 <= data["nominal_kw"] <= 3.6
        ):
            obj.configure(data["tank_litres"], data["nominal_kw"])
        for key in (
            "integrated_kwh",
            "covered_seconds",
            "gaps",
            "counter_epochs",
            "counter_delta_kwh",
        ):
            value = data.get(key)
            if _finite(value) and value >= 0:
                setattr(obj, key, value)
        counter = data.get("counter")
        if (
            isinstance(counter, dict)
            and _at(counter.get("at")) is not None
            and _finite(counter.get("kwh"))
            and counter["kwh"] >= 0
            and isinstance(counter.get("identity"), str)
        ):
            obj.counter = counter
        sessions = data.get("sessions", [])
        if isinstance(sessions, list):
            for row in sessions[-MAX_SESSIONS:]:
                if (
                    isinstance(row, dict)
                    and _at(row.get("at")) is not None
                    and _finite(row.get("kwh_per_c"))
                    and _finite(row.get("tank_litres", 315))
                    and 50 <= row.get("tank_litres", 315) <= 500
                    and 0.5 * row.get("tank_litres", 315) * 4.186 / 3600
                    <= row["kwh_per_c"]
                    <= 1.5 * row.get("tank_litres", 315) * 4.186 / 3600
                    and _finite(row.get("kw"))
                    and 0.5 <= row["kw"] <= 5
                ):
                    obj.sessions.append(
                        {
                            **row,
                            "target_c": row.get("target_c") if data["version"] == 2 else None,
                            "legacy_unclassified": data["version"] == 1
                            or row.get("legacy_unclassified", False),
                        }
                    )
        obj._saved_sessions = len(obj.sessions)
        obj.meter_identity = (
            data.get("meter_identity", "")
            if isinstance(data.get("meter_identity", ""), str)
            else ""
        )
        return obj

    def counter_update(self, at, kwh, identity):
        if kwh is None:
            return
        old = self.counter
        if old and at <= _at(old["at"]):
            return
        if old:
            hours = (at - _at(old["at"])).total_seconds() / 3600
            delta = kwh - old["kwh"]
            if (
                identity != old["identity"]
                or not 0 <= delta <= self.nominal_kw * 3.8 / 3 * hours + 0.02
            ):
                self.counter_epochs += 1  # reset, remap or impossible jump: re-anchor
            else:
                self.counter_delta_kwh += delta
        self.counter = {"at": at.isoformat(), "kwh": kwh, "identity": identity}

    def _end_session(self, at):
        if not self.dirty and self.candidate and self.candidate["rise"] >= 2:
            c = self.candidate
            self.sessions.append(
                {
                    "at": at.isoformat(),
                    "kwh_per_c": c["energy"] / c["rise"],
                    "kw": c["energy"] / c["hours"],
                    "target_c": self.last[2][1],
                    "tank_litres": self.tank_litres,
                    "nominal_kw": self.nominal_kw,
                    "model_version": 1,
                    "meter_identity": self.meter_identity,
                    "started_at": self.cycle["started_at"] if self.cycle else c["started_at"],
                    "complete_start": bool(self.cycle and self.cycle["complete_start"]),
                    "covered_cycle_energy_kwh": max(0, self.integrated_kwh - self.cycle["energy"])
                    if self.cycle
                    else None,
                    "fit_rise_c": c["rise"],
                    "fit_hours": c["hours"],
                    "fit_energy_kwh": c["energy"],
                    "fit_started_at": c["started_at"],
                    "fit_ended_at": c["ended_at"],
                    "temperature_start_c": c["temperature_start_c"],
                    "temperature_end_c": c["temperature_end_c"],
                    "quality": "clean_covered_fit",
                    "possible_draw": False,
                    "time_basis": "ha_receipt_not_device_acquisition",
                }
            )
        self.candidate = None
        self.dirty = False
        self.cycle = None

    def update(self, power, temperature, poll_at, mode, target, command_key=None, max_gap=120):
        if not power.valid:
            if self.last is not None:
                self.gaps += 1
            self.last = self.anchor = self.candidate = None
            self.cycle = None
            self.dirty = True
            return
        at, watts = power.observed_at, power.watts
        if self.last and at <= self.last[0]:
            return  # duplicate callbacks cannot add energy or learning evidence
        continuous = False
        on_hours = 0.0
        if self.last:
            seconds = (at - self.last[0]).total_seconds()
            continuous = 0 < seconds <= max_gap
            if continuous:
                self.integrated_kwh += (watts + self.last[1]) / 2 / 1000 * seconds / 3600
                self.covered_seconds += seconds
                if self.last[1] >= self.nominal_kw * 2000 / 3 and power.state == "on":
                    on_hours = seconds / 3600
            else:
                self.gaps += 1
                self.anchor = self.candidate = None
                self.dirty = self.last[1] >= self.nominal_kw * 2000 / 3
                self.cycle = None
        key = (mode, target, command_key)
        if self.last and key != self.last[2]:
            self.anchor = self.candidate = None
            self.dirty = True
            self.cycle = None
        if self.last and self.last[1] <= 100 and power.state == "on":
            self.dirty = False  # a new physically observed cycle
            self.cycle = {
                "started_at": at.isoformat(),
                "complete_start": continuous,
                "energy": self.integrated_kwh,
            }
        elif self.cycle is None and power.state == "on":
            self.cycle = {
                "started_at": at.isoformat(),
                "complete_start": False,
                "energy": self.integrated_kwh,
            }
        if power.state == "off":
            self._end_session(at)
            self.anchor = None
        # Only distinct genuine cloud observations bracket calibration. Every
        # included interval must be continuously measured ON under one target.
        if self.anchor and (not continuous or not on_hours):
            self.anchor = self.candidate = None
        if self.anchor:
            self.anchor["on_hours"] += on_hours
        valid_temp = (
            temperature is not None
            and _finite(temperature)
            and 0 <= temperature <= 90
            and poll_at is not None
            and 0 <= (at - poll_at).total_seconds() <= 120
        )
        if valid_temp and power.state == "on" and mode == "Manual" and target in (45, 62, 70):
            if self.anchor and poll_at > self.anchor["at"]:
                a = self.anchor
                hours = (poll_at - a["at"]).total_seconds() / 3600
                rise = temperature - a["temperature"]
                energy = self.integrated_kwh - a["energy"]
                slope = energy / rise if rise > 0 else 0
                if (
                    1 / 3 <= hours <= 1.5
                    and a["on_hours"] >= 0.95 * hours
                    and rise >= 2
                    and 0.5 * self.physics <= slope <= 1.5 * self.physics
                ):
                    if self.candidate is None:
                        self.candidate = {
                            "rise": 0.0,
                            "energy": 0.0,
                            "hours": 0.0,
                            "started_at": a["at"].isoformat(),
                            "temperature_start_c": a["temperature"],
                        }
                    self.candidate["rise"] += rise
                    self.candidate["energy"] += energy
                    self.candidate["hours"] += a["on_hours"]
                    self.candidate.update(
                        ended_at=poll_at.isoformat(), temperature_end_c=temperature
                    )
                else:
                    self.candidate = None  # draw, stratification spike or incomplete coverage
                    self.dirty = True
            if self.anchor is None or poll_at > self.anchor["at"]:
                self.anchor = {
                    "at": poll_at,
                    "temperature": temperature,
                    "energy": self.integrated_kwh,
                    "on_hours": 0.0,
                }
        self.last = (at, watts, key)

    def calibration(self, target=None):
        rows = [
            s
            for s in self.sessions
            if not s.get("legacy_unclassified", False)
            and s.get("target_c") in (45, 62, 70)
            and (target is None or s["target_c"] == target)
            and s.get("tank_litres") == self.tank_litres
            and s.get("nominal_kw") == self.nominal_kw
            and (not self.meter_identity or s.get("meter_identity") == self.meter_identity)
        ]
        days = {_at(s["at"]).date() for s in rows}
        ready = len(rows) >= 10 and len(days) >= 3
        return {
            "sessions": len(rows),
            "days": len(days),
            "ready": ready,
            "target_c": target,
            "kwh_per_c": median(s["kwh_per_c"] for s in rows) if ready else self.physics,
            "on_kw": median(s["kw"] for s in rows) if ready else self.nominal_kw,
            "affects_control": False,
        }

    def completion(self, now, temperature, poll_at, target, power):
        result = {
            "basis": "provisional_bottom_sensor",
            "continuous_minutes_low": None,
            "continuous_minutes_high": None,
            "earliest": None,
            "latest": None,
            "reported_target_reached": False,
            "state": "unknown",
            "nominal_continuous_minutes": None,
        }
        if (
            temperature is None
            or poll_at is None
            or target not in (45, 62, 70)
            or not 0 <= (now - poll_at).total_seconds() <= 45 * 60
        ):
            return result
        result["reported_target_reached"] = temperature >= target
        # Conditional duration only: no CT means no verified switch state or
        # promised wall time. Stale probes never seed a nominal prediction.
        result["nominal_continuous_minutes"] = round(
            max(0, target - temperature) * self.physics / self.nominal_kw * 60, 1
        )
        if not power.valid or power.state != "on":
            result["state"] = "idle_next_cut_in_unknown" if power.valid else "meter_unknown"
            return result
        c = self.calibration(target)
        energy = max(0.0, target - temperature) * c["kwh_per_c"]
        # Only covered measured energy since this genuine temperature anchor
        # reduces the estimate. Unknown draws still invalidate any guarantee.
        covered = 0.0
        if self.anchor and self.anchor["at"] == poll_at and self.last and self.last[2][1] == target:
            covered = max(0, self.integrated_kwh - self.anchor["energy"])
        low = max(0, energy * 0.67 - covered * 1.03) / (self.nominal_kw * 3.8 / 3) * 60
        high = max(0, energy * 1.5 - covered * 0.97) / (self.nominal_kw * 2 / 3) * 60
        result["measured_kwh_since_anchor"] = round(covered, 4)
        result.update(
            state="conditional_continuous_heating",
            basis="measured_sessions" if c["ready"] else result["basis"],
            continuous_minutes_low=round(low, 1),
            continuous_minutes_high=round(high, 1),
            earliest=(now + timedelta(minutes=low)).isoformat(),
            latest=(now + timedelta(minutes=high)).isoformat(),
        )
        return result

    def should_save(self, now):
        changed = len(self.sessions) != self._saved_sessions
        due = self._saved_at is None or now - self._saved_at >= SAVE_INTERVAL
        if changed or due:
            self._saved_at, self._saved_sessions = now, len(self.sessions)
            return True
        return False
