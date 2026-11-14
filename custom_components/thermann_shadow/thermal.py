"""Read-only thermal OBSERVER for the Thermann 315 L / 3 kW tank (0.7.0).

Diagnostics and evidence collection only. Nothing here feeds the planner, the
controller or any heater command, and nothing causes a cloud request: it uses
the 30-minute Thermann readings already polled, the element state already
estimated from the GoodWe/HK1000 meter, and the clock.

Thermann's sensor is near the BOTTOM of the tank. A shower lets cold mains
water in at the bottom, so the reading can fall sharply while plenty of hot
water remains at the top, then rebound as the tank settles. A reading is
therefore never treated as the temperature of every litre or as proof of
shower availability, and every output is labelled as measured, estimated or
inferred, with a confidence.

Tank states (inferred):
- ``heating`` / ``heating_after_draw``: the element is drawing power;
- ``settling_after_heating``: heating ended in the last 90 minutes (the
  bottom reading lags and can overshoot or fall back); ``thermostat_satisfied``
  is recorded when it ended with Manual still selected;
- ``draw_suspected``: a reading fell at least 3 °C in one poll interval with no
  heating (water use is LIKELY, not proven);
- ``settling_after_draw``: within 3 hours of a suspected draw (rebound tracked);
- ``stable``: none of the above, with recent readings;
- ``unknown``: not enough data.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from statistics import median

from .model import ELEMENT_KW, TANK_KWH_PER_C

DRAW_DROP_C = 3.0  # fall in one poll interval with no heating
LARGE_DRAW_DROP_C = 8.0
REBOUND_C = 1.5
DRAW_SETTLE = timedelta(hours=3)
HEAT_SETTLE = timedelta(minutes=90)
DRAW_FRESH = timedelta(minutes=35)
COOLING_SPAN = timedelta(hours=3)  # whole-degree readings: measure over hours
MIN_SESSION_MINUTES = 5
PHYSICAL_C_PER_KWH = 1 / TANK_KWH_PER_C  # fully mixed 315 L: ~2.73 °C/kWh
MAX_SESSIONS, MAX_DRAWS, MAX_COOLING = 30, 30, 60
CONFIDENT = {"verified", "high", "medium"}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class ThermalObserver:
    def __init__(self) -> None:
        self.last_tick: datetime | None = None
        self.poll_at: datetime | None = None
        self.reading: float | None = None
        self.previous: tuple[datetime, float] | None = None  # earlier poll
        self.interval_change_c_per_hour: float | None = None
        self.energy_since_poll = 0.0
        self.energy_unknown_since_poll = False
        self.element_on = False
        self.session: dict | None = None
        self.last_heating_end: datetime | None = None
        self.last_end_satisfied = False
        self.pending_end: dict | None = None  # session awaiting its next reading
        self.anchor: tuple[datetime, float] | None = None  # start of an undisturbed span
        self.last_draw: dict | None = None
        self.sessions: deque[dict] = deque(maxlen=MAX_SESSIONS)
        self.draws: deque[dict] = deque(maxlen=MAX_DRAWS)
        self.cooling: deque[dict] = deque(maxlen=MAX_COOLING)
        self.state, self.confidence, self.basis = "unknown", "none", []
        self.dirty = False
        self.saved_at: datetime | None = None

    # ------------------------------------------------------------------ update
    def update(
        self,
        now: datetime,
        reading: float | None,
        poll_at: datetime | None,
        element: str,
        element_confidence: str,
        mode: str | None,
        *,
        heater_power_kw: float | None = None,
        meter_configured: bool = False,
    ) -> None:
        # Preserve nominal-energy historical diagnostics only while no dedicated
        # circuit meter is configured. Once configured, incomplete readings must
        # not silently contaminate the thermal calibration with inferred 3 kW.
        meter_missing = meter_configured and heater_power_kw is None
        on = element == "on" and element_confidence in CONFIDENT and not meter_missing
        if meter_missing:
            self.energy_unknown_since_poll = True
            if self.session is not None:
                self.session["meter_gap"] = True
        if self.last_tick is not None and on:
            step = min(timedelta(minutes=2), max(timedelta(0), now - self.last_tick))
            kw = heater_power_kw if meter_configured else ELEMENT_KW
            kwh = kw * step.total_seconds() / 3600
            self.energy_since_poll += kwh
            if self.session is not None:
                self.session["energy_kwh"] += kwh
        self.last_tick = now
        if on and not self.element_on:
            self._start_session(now, meter_configured)
        elif not on and self.element_on:
            self._end_session(now, mode, meter_missing)
        self.element_on = on
        if reading is not None and poll_at is not None and poll_at != self.poll_at:
            self._new_reading(poll_at, reading)
        self._classify(now, element_confidence)

    def _start_session(self, now: datetime, meter_configured: bool = False) -> None:
        recent_draw = self.last_draw is not None and now - _dt(self.last_draw["at"]) <= DRAW_SETTLE
        self.session = {
            "start": _iso(now),
            "start_reading": self.reading,
            "start_reading_at": _iso(self.poll_at),
            "energy_kwh": 0.0,
            "energy_source": "circuit_meter" if meter_configured else "nominal_element",
            "meter_gap": False,
            "after_draw": recent_draw,
        }
        self.anchor = None

    def _end_session(self, now: datetime, mode: str | None, meter_missing: bool = False) -> None:
        session, self.session = self.session, None
        self.last_heating_end = now
        self.last_end_satisfied = mode == "Manual" and not meter_missing
        if session is None:
            return
        if meter_missing:
            session["meter_gap"] = True
        minutes = (now - _dt(session["start"])).total_seconds() / 60
        if minutes < MIN_SESSION_MINUTES:
            return
        start = session["start_reading"]
        predicted = (
            max(0.0, 70.0 - start) * TANK_KWH_PER_C / ELEMENT_KW * 60 if start is not None else None
        )
        session.update(
            end=_iso(now),
            minutes=round(minutes, 1),
            energy_kwh=round(session["energy_kwh"], 3),
            thermostat_satisfied=self.last_end_satisfied,
            physical_model_minutes_to_70=round(predicted, 1) if predicted is not None else None,
            end_reading=None,
        )
        self.pending_end = session

    def _new_reading(self, poll_at: datetime, reading: float) -> None:
        if self.poll_at is not None and self.reading is not None:
            self.previous = (self.poll_at, self.reading)
            hours = (poll_at - self.poll_at).total_seconds() / 3600
            change = reading - self.reading
            self.interval_change_c_per_hour = change / hours if hours > 0 else None
            heated = self.energy_since_poll >= 0.1
            if self.energy_unknown_since_poll:
                # No reliable draw or cooling inference over a meter-data gap.
                self.anchor = None
            else:
                if heated:
                    self.anchor = None
                elif change <= -DRAW_DROP_C:
                    self._record_draw(poll_at, reading, change)
                elif (
                    change >= REBOUND_C
                    and self.last_draw is not None
                    and poll_at - _dt(self.last_draw["at"]) <= DRAW_SETTLE
                ):
                    self.last_draw["rebound_c"] = round(
                        self.last_draw.get("rebound_c", 0.0) + change, 1
                    )
                    self.dirty = True
                self._track_cooling(poll_at, reading, heated)
        if self.pending_end is not None:
            session, self.pending_end = self.pending_end, None
            session["end_reading"] = reading
            start = session["start_reading"]
            if start is not None and session["energy_kwh"] > 0.05 and not session.get("meter_gap"):
                session["observed_c_per_kwh"] = round((reading - start) / session["energy_kwh"], 2)
            self.sessions.append(session)
            self.dirty = True
        self.poll_at, self.reading = poll_at, reading
        self.energy_since_poll = 0.0
        self.energy_unknown_since_poll = False

    def _record_draw(self, at: datetime, reading: float, change: float) -> None:
        after_heating = (
            self.last_heating_end is not None and at - self.last_heating_end <= HEAT_SETTLE
        )
        if after_heating:
            confidence = "low"  # could be post-heating settling of the bottom sensor
        else:
            confidence = "high" if -change >= LARGE_DRAW_DROP_C else "medium"
        self.last_draw = {
            "at": _iso(at),
            "drop_c": round(-change, 1),
            "reading_before": self.reading,
            "reading_after": reading,
            "confidence": confidence,
            "basis": "bottom_reading_fell_without_heating",
        }
        self.draws.append(self.last_draw)
        self.anchor = None
        self.dirty = True

    def _track_cooling(self, at: datetime, reading: float, heated: bool) -> None:
        disturbed = (
            heated
            or (self.last_draw is not None and at - _dt(self.last_draw["at"]) <= DRAW_SETTLE)
            or (self.last_heating_end is not None and at - self.last_heating_end <= HEAT_SETTLE)
        )
        if disturbed:
            self.anchor = None
            return
        if self.anchor is None:
            self.anchor = (at, reading)
            return
        span = at - self.anchor[0]
        if span >= COOLING_SPAN:
            hours = span.total_seconds() / 3600
            self.cooling.append(
                {
                    "end": _iso(at),
                    "hours": round(hours, 2),
                    "from_c": self.anchor[1],
                    "to_c": reading,
                    "c_per_hour": round((self.anchor[1] - reading) / hours, 3),
                }
            )
            self.anchor = (at, reading)
            self.dirty = True

    def _classify(self, now: datetime, element_confidence: str) -> None:
        draw_at = _dt(self.last_draw["at"]) if self.last_draw else None
        if self.element_on:
            after = draw_at is not None and now - draw_at <= DRAW_SETTLE
            self.state = "heating_after_draw" if after else "heating"
            self.confidence = "high" if element_confidence in {"verified", "high"} else "medium"
            self.basis = ["element_drawing_power_by_meter"]
        elif self.last_heating_end is not None and now - self.last_heating_end <= HEAT_SETTLE:
            self.state = "settling_after_heating"
            self.confidence = "medium"
            self.basis = ["heating_ended_recently"] + (
                ["ended_with_manual_selected_thermostat_satisfied"]
                if self.last_end_satisfied
                else []
            )
        elif draw_at is not None and now - draw_at <= DRAW_SETTLE:
            fresh = now - draw_at <= DRAW_FRESH
            self.state = "draw_suspected" if fresh else "settling_after_draw"
            self.confidence = self.last_draw["confidence"]
            self.basis = ["bottom_reading_fell_without_heating"]
        elif self.previous is not None:
            self.state, self.confidence, self.basis = "stable", "medium", ["no_recent_event"]
        else:
            self.state, self.confidence, self.basis = "unknown", "none", ["insufficient_readings"]

    # ------------------------------------------------------------------ outputs
    def standing_loss(self) -> tuple[float | None, int]:
        rates = [item["c_per_hour"] for item in self.cooling]
        return (round(median(rates), 3) if rates else None), len(rates)

    def summary(self, now: datetime) -> dict:
        loss, loss_n = self.standing_loss()
        done = [s for s in self.sessions if s.get("observed_c_per_kwh") is not None]

        def perf(group):
            values = [s["observed_c_per_kwh"] for s in group]
            return (
                {"median_c_per_kwh": round(median(values), 2), "sessions": len(values)}
                if values
                else None
            )

        ratios = [
            s["minutes"] / s["physical_model_minutes_to_70"]
            for s in self.sessions
            if s.get("thermostat_satisfied") and s.get("physical_model_minutes_to_70")
        ]
        remaining = None
        if self.element_on and self.reading is not None:
            remaining = round(max(0.0, 70.0 - self.reading) * TANK_KWH_PER_C / ELEMENT_KW * 60)
        return {
            "affects_control": False,
            "state": self.state,
            "confidence": self.confidence,
            "basis": self.basis,
            "measured": {
                "last_reading_c": self.reading,
                "reading_age_minutes": round((now - self.poll_at).total_seconds() / 60)
                if self.poll_at
                else None,
                "observed_change_c_per_hour": round(self.interval_change_c_per_hour, 2)
                if self.interval_change_c_per_hour is not None
                else None,
            },
            "estimated": {
                "session_energy_kwh": round(self.session["energy_kwh"], 3) if self.session else 0.0,
                "remaining_heating_minutes_physical_upper_bound": remaining,
                "standing_loss_c_per_hour": loss,
                "standing_loss_samples": loss_n,
                "physical_model_c_per_kwh": round(PHYSICAL_C_PER_KWH, 2),
            },
            "inferred": {
                "last_suspected_draw": self.last_draw,
                "heating_after_draw": perf([s for s in done if s.get("after_draw")]),
                "heating_undisturbed": perf([s for s in done if not s.get("after_draw")]),
                "metered_heating_undisturbed": perf(
                    [
                        s
                        for s in done
                        if s.get("energy_source") == "circuit_meter" and not s.get("after_draw")
                    ]
                ),
                "actual_vs_physical_minutes_median": round(median(ratios), 2) if ratios else None,
                "satisfied_sessions": len(ratios),
            },
            "recent_sessions": list(self.sessions)[-5:],
        }

    # ------------------------------------------------------------------ persistence
    def to_dict(self) -> dict:
        return {
            "version": 1,
            "sessions": list(self.sessions),
            "draws": list(self.draws),
            "cooling": list(self.cooling),
            "last_draw": self.last_draw,
        }

    @classmethod
    def from_dict(cls, data) -> ThermalObserver:
        observer = cls()
        if isinstance(data, dict) and data.get("version") == 1:
            for key, target in (
                ("sessions", observer.sessions),
                ("draws", observer.draws),
                ("cooling", observer.cooling),
            ):
                items = data.get(key)
                if isinstance(items, list):
                    target.extend(item for item in items if isinstance(item, dict))
            if isinstance(data.get("last_draw"), dict):
                observer.last_draw = data["last_draw"]
        return observer

    def should_save(self, now: datetime) -> bool:
        """Only when evidence changed, at most every 10 minutes (no per-minute writes)."""
        if not self.dirty:
            return False
        if self.saved_at is not None and now - self.saved_at < timedelta(minutes=10):
            return False
        self.saved_at, self.dirty = now, False
        return True
