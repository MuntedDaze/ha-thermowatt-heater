"""Compact measured-energy history and cautious bottom-sensor calibration.

No cloud reads or commands. HA Recorder owns the raw timeline. Power integration
never bridges a missing report or restart. Learned slopes are diagnostics until
independent validation; a single probe cannot establish whole-tank heat/comfort.
"""

from collections import deque
from datetime import datetime, timedelta
import math
from statistics import median

from .model import TANK_KWH_PER_C, UTC

MAX_SESSIONS = 40
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
    def __init__(self):
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

    def to_dict(self):
        return {
            "version": 1,
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
        if not isinstance(data, dict) or data.get("version") != 1:
            return obj
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
                    and 0.5 * TANK_KWH_PER_C <= row["kwh_per_c"] <= 1.5 * TANK_KWH_PER_C
                    and _finite(row.get("kw"))
                    and 2 <= row["kw"] <= 3.8
                ):
                    obj.sessions.append(row)
        obj._saved_sessions = len(obj.sessions)
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
            if identity != old["identity"] or not 0 <= delta <= 3.8 * hours + 0.02:
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
                }
            )
        self.candidate = None
        self.dirty = False

    def update(self, power, temperature, poll_at, mode, target, command_key=None, max_gap=120):
        if not power.valid:
            if self.last is not None:
                self.gaps += 1
            self.last = self.anchor = self.candidate = None
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
                if self.last[1] >= 2000 and watts >= 2000:
                    on_hours = seconds / 3600
            else:
                self.gaps += 1
                self.anchor = self.candidate = None
                self.dirty = self.last[1] >= 2000
        key = (mode, target, command_key)
        if self.last and key != self.last[2]:
            self.anchor = self.candidate = None
            self.dirty = True
        if self.last and self.last[1] <= 100 and power.state == "on":
            self.dirty = False  # a new physically observed cycle
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
        if valid_temp and power.state == "on" and mode == "Manual" and target in (45, 70):
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
                    and 0.5 * TANK_KWH_PER_C <= slope <= 1.5 * TANK_KWH_PER_C
                ):
                    if self.candidate is None:
                        self.candidate = {"rise": 0.0, "energy": 0.0, "hours": 0.0}
                    self.candidate["rise"] += rise
                    self.candidate["energy"] += energy
                    self.candidate["hours"] += a["on_hours"]
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

    def calibration(self):
        days = {_at(s["at"]).date() for s in self.sessions}
        ready = len(self.sessions) >= 10 and len(days) >= 3
        return {
            "sessions": len(self.sessions),
            "days": len(days),
            "ready": ready,
            "kwh_per_c": median(s["kwh_per_c"] for s in self.sessions) if ready else TANK_KWH_PER_C,
            "on_kw": median(s["kw"] for s in self.sessions) if ready else 3.0,
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
        }
        if (
            temperature is None
            or poll_at is None
            or target not in (45, 70)
            or not 0 <= (now - poll_at).total_seconds() <= 45 * 60
        ):
            return result
        result["reported_target_reached"] = temperature >= target
        if not power.valid or power.state != "on":
            result["state"] = "idle_next_cut_in_unknown" if power.valid else "meter_unknown"
            return result
        c = self.calibration()
        energy = max(0.0, target - temperature) * c["kwh_per_c"]
        # No subtraction of unobserved heat/draws; wide conditional interval.
        low, high = energy * 0.67 / 3.8 * 60, energy * 1.5 / 2.0 * 60
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
