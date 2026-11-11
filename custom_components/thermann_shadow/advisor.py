"""Per-minute read-only hot-water advice. HA-independent; never a command.

Separates what is MEASURED (meter, PV, reading), what is ESTIMATED (element
state, base load) and what is HYPOTHETICAL (the planner's proposed plan). The
native Schedule is treated as the real controller and modelled separately.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import statistics

from .goals import upcoming_goals
from .heater_state import HeaterState, HeaterStateEstimator, base_load
from .model import Plan, Settings, Tariff
from .strategy import Assessment, assess, build_slots, native_outlook

BASE_WINDOW = timedelta(minutes=60)
METER_SUSPECT_AFTER = timedelta(minutes=10)
GATE_STATES = {
    "shadow_paused": (
        "paused",
        "PAUSED",
        "Shadow planning is paused by the owner. Native Schedule continues.",
    ),
    "shadow_native_intervention": (
        "owner_review_required",
        "OWNER REVIEW",
        "The heater's native mode or target changed. Planning is latched for owner review; nothing is sent to the heater.",
    ),
    "shadow_blocked": (
        "data_unavailable",
        "DATA UNAVAILABLE",
        "A fresh, healthy heater status and meter reading are needed. Native Schedule remains the real comfort fallback.",
    ),
    "shadow_awaiting_validation": (
        "data_unavailable",
        "DATA UNAVAILABLE",
        "Meter sign/units and the tariff must be confirmed before advice is given.",
    ),
}
IMMEDIATE = {"heat_now_comfort_fallback", "insufficient_time", "no_heating_needed"}
GATE_CODES = {"data_unavailable", "paused", "owner_review_required"}
SATISFIED_RESET_DROP_C = 5.0  # reading fall that invalidates a thermostat-satisfied event


@dataclass
class TickInputs:
    temperature: float | None
    house_kw: float | None
    pv_ac_kw: float | None
    export_kw: float | None
    status_raw: object
    status_at: datetime | None
    in_window: object  # callable(datetime) -> bool
    heater_power_kw: float | None = None
    pv_series: tuple = ()
    load_series: tuple = ()
    forecast_available: bool = False


@dataclass
class Advice:
    code: str
    label: str
    explanation: str
    confidence: str
    heater: HeaterState
    base_low_kw: float | None = None
    base_high_kw: float | None = None
    base_p50_kw: float | None = None
    surplus_now_kw: float | None = None
    meter_suspect: bool = False
    assessment: Assessment | None = None
    native: dict | None = None
    pending_code: str | None = None
    readiness: dict = field(default_factory=dict)
    goals: list = field(default_factory=list)


class Advisor:
    def __init__(self) -> None:
        self.estimator = HeaterStateEstimator()
        self.base_samples: deque[tuple[datetime, float, float]] = deque(maxlen=120)
        self.zero_meter_since: datetime | None = None
        self.shown: tuple[str, str, str, str] | None = None
        self.candidate: tuple[str, datetime] | None = None
        self.previous_state: str | None = None
        self.on_since: datetime | None = None
        # (time, reading) when the element switched off INSIDE a permitted native
        # window: the native thermostat (which uses its own sensor) was satisfied.
        self.satisfied: tuple[datetime, float] | None = None

    def reset(self) -> None:
        self.__init__()

    def _meter_suspect(self, now: datetime, inputs: TickInputs) -> bool:
        """HK1000 pre-commissioning signature: exactly 0 W while PV produces."""
        if (
            inputs.export_kw is not None
            and abs(inputs.export_kw) < 0.001
            and (inputs.pv_ac_kw or 0) > 0.3
        ):
            self.zero_meter_since = self.zero_meter_since or now
        else:
            self.zero_meter_since = None
        return (
            self.zero_meter_since is not None and now - self.zero_meter_since >= METER_SUSPECT_AFTER
        )

    def _stabilise(self, now: datetime, decision: tuple[str, str, str, str], hold_minutes: float):
        code = decision[0]
        if (
            self.shown is None
            or code in IMMEDIATE
            or code in GATE_CODES
            or self.shown[0] in GATE_CODES
            or code == self.shown[0]
        ):
            self.shown, self.candidate = decision, None
            return decision, None
        if self.candidate is None or self.candidate[0] != code:
            self.candidate = (code, now)
        if now - self.candidate[1] >= timedelta(minutes=hold_minutes):
            self.shown, self.candidate = decision, None
            return decision, None
        return self.shown, code  # keep the previous advice while the new one persists

    def tick(
        self,
        now: datetime,
        plan: Plan,
        settings: Settings,
        tariffs: tuple[Tariff, ...],
        inputs: TickInputs,
    ) -> Advice:
        suspect = self._meter_suspect(now, inputs)
        house = None if suspect else inputs.house_kw
        try:
            window = bool(inputs.in_window(now))
        except Exception:  # noqa: BLE001 - reference data only
            window = None
        heater = self.estimator.update(
            now, house, inputs.status_raw, inputs.status_at, window, inputs.heater_power_kw
        )
        self._track_satisfaction(now, heater, inputs)
        low, high = base_load(house, heater)
        if low is not None:
            self.base_samples.append((now, low, high))
        while self.base_samples and now - self.base_samples[0][0] > BASE_WINDOW:
            self.base_samples.popleft()
        lows = [item[1] for item in self.base_samples]
        highs = [item[2] for item in self.base_samples]
        base_p50 = statistics.median(lows) if lows else low
        base_p90 = sorted(highs)[min(len(highs) - 1, int(0.9 * len(highs)))] if highs else high
        advice = Advice("data_unavailable", "DATA UNAVAILABLE", "", "none", heater)
        advice.meter_suspect = suspect
        advice.base_low_kw, advice.base_high_kw, advice.base_p50_kw = low, high, base_p50
        if inputs.pv_ac_kw is not None and base_p50 is not None:
            advice.surplus_now_kw = round(
                max(0.0, min(settings.pv_ac_limit_kw, inputs.pv_ac_kw) - base_p50), 3
            )
        goals = upcoming_goals(now, settings, tariffs)[:2]
        advice.goals = goals
        gate = GATE_STATES.get(plan.state)
        if suspect and gate is None:
            gate = (
                "data_unavailable",
                "DATA UNAVAILABLE",
                "The grid meter reads exactly 0 W while solar is producing, as it did before the "
                "HK1000 was commissioned. House load cannot be trusted.",
            )
        if gate is not None or inputs.temperature is None or not goals:
            gate = gate or GATE_STATES["shadow_blocked"]
            shown, pending = self._stabilise(now, (*gate, "none"), settings.solar_hold_minutes)
            advice.code, advice.label, advice.explanation, advice.confidence = shown
            advice.pending_code = pending
            return advice
        horizon = max(goal.deadline for goal in goals)
        slots = build_slots(
            now,
            horizon,
            settings,
            tariffs,
            inputs.pv_ac_kw,
            (base_p50 if heater.state != "unknown" else low, high),
            base_p90,
            inputs.pv_series,
            inputs.load_series,
        )
        native = native_outlook(
            now,
            inputs.temperature,
            goals,
            slots,
            settings,
            lambda at: _safe_window(inputs.in_window, at),
            heater.state == "on",
        )
        result = assess(
            now,
            inputs.temperature,
            goals,
            slots,
            settings,
            heater.state,
            inputs.forecast_available,
            native,
            storage_satisfied=self.satisfied is not None,
        )
        advice.assessment, advice.native = result, native
        best = result.plans.get("best_overall")
        for goal, kwh in result.requirements:
            if kwh <= 1e-9:
                status = "met"
            elif result.code == "insufficient_time":
                status = "shortfall"
            elif best is not None and best.feasible:
                status = "on_track"
            else:
                status = "at_risk"
            advice.readiness[goal.kind] = {
                "status": status,
                "deadline": goal.deadline,
                "required_kwh": round(kwh, 3),
                "basis": goal.basis,
                "target_c": goal.target_c,
                "native_meets": native["readiness"].get(goal.kind, {}).get("met"),
            }
        shown, pending = self._stabilise(
            now,
            (result.code, result.label, result.explanation, result.confidence),
            settings.solar_hold_minutes,
        )
        advice.code, advice.label, advice.explanation, advice.confidence = shown
        advice.pending_code = pending
        return advice

    def _track_satisfaction(self, now, heater, inputs) -> None:
        reading = inputs.temperature
        if self.satisfied and reading is not None:
            if reading < self.satisfied[1] - SATISFIED_RESET_DROP_C:
                self.satisfied = None  # water was used; storage must be rebuilt
        if heater.state == "on" and heater.confidence in {"verified", "high"}:
            self.satisfied = None
        if heater.state == "on" and self.previous_state != "on":
            self.on_since = now
        heated_long_enough = self.on_since is not None and now - self.on_since >= timedelta(
            minutes=10
        )
        if (
            self.previous_state == "on"
            and heater.state == "off"
            and heated_long_enough
            and reading is not None
            and _safe_window(inputs.in_window, now)
            and _safe_window(inputs.in_window, now + timedelta(minutes=10))
        ):
            self.satisfied = (now, reading)
        self.previous_state = heater.state


def _safe_window(function, at: datetime) -> bool:
    try:
        return bool(function(at))
    except Exception:  # noqa: BLE001 - reference data only
        return False
