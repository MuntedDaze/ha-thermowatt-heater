"""Simplified heating policy: DESIGN DRAFT, not used by the installed controller.

Nothing imports this module yet. It is the reviewable core of the proposed
simplification (see shadow_controller/SIMPLIFIED_STRATEGY.md). Wiring it into
the controller needs owner approval, and so does the bridge change it depends
on: today the bridge accepts only ``Manual:70`` and ``off``.

Three heater states, chosen from the tariff calendar, the Thermann reading and
LOCAL meter samples (GoodWe, about once a minute; never a cloud request):

  OFF       Thermann software OFF. Antibacterial and frost protection stay active.
  BASELINE  Manual at the baseline target. The native thermostat keeps comfort.
  STORAGE   Manual at the storage target (70 °C). Stores heat or uses solar.

The tariff calendar decides the mode:

  PEAK         a peak period, or the last ``peak_lead`` before one: OFF, or STORAGE
               while MEASURED solar qualifies (forecasts never count here).
  DEADLINE     daytime before an evening peak: wait (OFF or BASELINE, whichever
               the heater is in, so no command), then STORAGE until the peak.
               Storage starts at the LATEST time that still finishes before the
               peak, or earlier when measured solar is at least as cheap as the
               forecast later, when no solar is forecast, or when the tank is low.
  OPPORTUNITY  every other off-peak time: weekday nights and whole weekends.
               BASELINE, plus STORAGE while solar heating is worth it and can
               finish before the next peak.

Precedence, highest first (the caller supplies layers 1-3):

  1. Manufacturer protective heating (antibacterial, frost): HOLD, never a command.
  2. Owner: app change / hold (HOLD), holiday (OFF), 12hr Override (STORAGE).
  3. Cloud, authentication, freshness and command spacing: may only BLOCK sending.
  4. Peak import restriction (PEAK mode).
  5. Hot-water comfort and economical heating (DEADLINE / OPPORTUNITY).
  6. Forecast optimisation (only ever delays or advances an off-peak start).

Timers: one solar qualification (10 min), one withdrawal (5 min), one command
spacing (15 min). There is no minimum run or minimum rest: the thermostat, not
this policy, switches the element.

Pure: no Home Assistant, no I/O. One instance per controller keeps the meter
samples; ``decide`` is deterministic for a given history.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median

from .model import ELEMENT_KW, HOBART, TANK_KWH_PER_C, Forecast, Tariff, tariff_at

OFF, BASELINE, STORAGE, HOLD = "off", "baseline", "storage", "hold"
STATES = (OFF, BASELINE, STORAGE)
PEAK, DEADLINE, OPPORTUNITY = "peak", "deadline", "opportunity"
PRICE_TOLERANCE = 0.005  # $/kWh: "no worse than" when comparing heating costs
SCAN_STEP = timedelta(minutes=15)
SCAN_HORIZON = timedelta(days=4)


@dataclass(frozen=True)
class PolicySettings:
    baseline_c: int = 45  # owner decision pending: see SIMPLIFIED_STRATEGY.md, section 3
    storage_c: int = 70
    hysteresis_c: float = 8.0  # Thermann guide p9: reheats about 8 °C below the target
    element_kw: float = ELEMENT_KW
    kwh_per_c: float = TANK_KWH_PER_C
    feed_in_rate: float = 0.09276
    tariff_clock: str = "standard"
    peak_start_kw: float = 3.3  # element 3.0 kW + 0.3 kW buffer
    peak_import_tolerance_kw: float = 0.2
    solar_floor_kw: float = 1.0  # least measured surplus considered off-peak
    solar_stop_margin_kw: float = 0.5  # opportunity ends below floor - margin
    optional_heat_margin: float = 0.02  # $/kWh saving needed for heat not otherwise needed
    qualify: timedelta = timedelta(minutes=10)
    withdraw: timedelta = timedelta(minutes=5)
    command_spacing: timedelta = timedelta(minutes=15)
    peak_lead: timedelta = timedelta(minutes=15)  # = spacing: OFF always lands by the peak
    finish_margin: timedelta = timedelta(minutes=30)
    daytime_from_hour: int = 9  # early storage starts only from here (local)
    evening_peak_from_hour: int = 12  # a peak starting at/after this is an evening peak
    reading_max_age: timedelta = timedelta(minutes=75)
    meter_max_age: timedelta = timedelta(minutes=3)

    def __post_init__(self) -> None:
        if not 40 <= self.baseline_c <= 65 or not 60 <= self.storage_c <= 70:
            raise ValueError("policy_targets_out_of_range")
        if self.storage_c - self.baseline_c < self.hysteresis_c:
            raise ValueError("policy_targets_too_close")
        if self.peak_start_kw < self.element_kw or self.solar_floor_kw <= self.solar_stop_margin_kw:
            raise ValueError("policy_solar_thresholds_invalid")
        if self.peak_lead < self.command_spacing:
            # A command just before the lead window could otherwise hold the
            # peak OFF back into the peak.
            raise ValueError("policy_peak_lead_below_spacing")


@dataclass(frozen=True)
class Snapshot:
    """What the caller knows now. Heater state is the CONFIRMED one."""

    now: datetime
    heater_state: str | None  # OFF / BASELINE / STORAGE, or None when anything else
    reading_c: float | None = None  # Thermann bottom-sensor reading
    reading_at: datetime | None = None  # bridge poll time of that reading
    forecast: tuple[Forecast, ...] = ()  # EMHASS net export (after household load)
    last_command_at: datetime | None = None
    heating_c_per_hour: float | None = None  # observed reading rise while heating
    # Precedence layers 1-3, decided by the existing controller and bridge.
    manufacturer_heating: bool = False
    owner_override: bool = False
    holiday: bool = False
    override_12h: bool = False
    cloud_ready: bool = True


@dataclass(frozen=True)
class Decision:
    state: str  # desired heater state, or HOLD (keep whatever it is)
    reason: str
    layer: int
    command: str | None = None  # MQTT MODE payload to send now, if any
    plan: dict = field(default_factory=dict)


class SimplePolicy:
    def __init__(self, settings: PolicySettings, tariffs: tuple[Tariff, ...]):
        self.s = settings
        self.tariffs = tariffs
        # (at, import_kw, available_kw); available EXCLUDES the element's own draw.
        self.samples: deque[tuple[datetime, float, float]] = deque()
        self._peak_cache: tuple[datetime, datetime | None, datetime] | None = None

    # --- local meter ---------------------------------------------------------------

    def add_meter(self, at: datetime, grid_kw: float, element_on: bool | None) -> None:
        """One local sample: grid import positive, export negative. ``element_on``
        is the caller's element estimate (house-load step); None counts as off,
        which can only make solar look SMALLER (never a costly start)."""
        available = -grid_kw + (self.s.element_kw if element_on else 0.0)
        self.samples.append((at, max(0.0, grid_kw), available))
        cutoff = at - 2 * max(self.s.qualify, self.s.withdraw)
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()

    def _window(self, now: datetime, window: timedelta):
        return [smp for smp in self.samples if now - window <= smp[0] <= now]

    def meter_fresh(self, now: datetime) -> bool:
        return bool(self.samples) and now - self.samples[-1][0] <= self.s.meter_max_age

    def sustained(self, now: datetime, window: timedelta, test) -> bool:
        """``test`` held for ``window``: samples cover the whole window (to within
        one minute) with no gap above the meter age limit, and at least 80 % of
        them pass (a kettle or a passing cloud for a minute or two does not
        reset it)."""
        recent = self._window(now, window)
        start = now - window + timedelta(minutes=1)
        if not recent or not self.meter_fresh(now) or recent[0][0] > start:
            return False
        if any(
            b[0] - a[0] > self.s.meter_max_age for a, b in zip(recent, recent[1:], strict=False)
        ):
            return False
        return sum(1 for smp in recent if test(smp)) >= 0.8 * len(recent)

    def typical_available(self, now: datetime) -> float | None:
        recent = self._window(now, self.s.qualify)
        return median(smp[2] for smp in recent) if recent else None

    # --- tariff calendar --------------------------------------------------------------

    def _kind(self, at: datetime) -> str:
        return tariff_at(at, self.tariffs, self.s.tariff_clock).kind

    def next_peak(self, now: datetime) -> datetime | None:
        """Start of the next peak strictly after ``now`` (``now`` not in a peak)."""
        cached = self._peak_cache  # (computed at, result, valid until)
        if cached and cached[0] <= now < cached[2]:
            return cached[1]
        at, found = now, None
        while at - now < SCAN_HORIZON:
            at += SCAN_STEP
            if self._kind(at) == "peak":
                found = at
                while self._kind(found - timedelta(minutes=1)) == "peak" and found > now:
                    found -= timedelta(minutes=1)
                break
        self._peak_cache = (now, found, found or now + timedelta(hours=1))
        return found

    # --- heating arithmetic --------------------------------------------------------------

    def _rate_c_per_hour(self, observed: float | None) -> float:
        physics = self.s.element_kw / self.s.kwh_per_c  # about 8.2 °C/h for 315 L, 3 kW
        if observed is None or observed <= 0:
            return physics
        return min(max(observed, 0.5 * physics), 1.5 * physics)

    def mixed_cost(self, surplus_kw: float, grid_rate: float) -> float:
        """$/kWh of heat when ``surplus_kw`` of solar covers part of the element."""
        solar = min(max(surplus_kw, 0.0), self.s.element_kw)
        return (solar * self.s.feed_in_rate + (self.s.element_kw - solar) * grid_rate) / (
            self.s.element_kw
        )

    @staticmethod
    def best_forecast_kw(forecast, start: datetime, end: datetime) -> float | None:
        """Best one-hour mean forecast export in [start, end]; None if the
        forecast covers less than 80 % of it (unknown, never "no solar")."""
        if end - start < timedelta(hours=1):
            return None
        slots = sorted(forecast, key=lambda f: f.start)
        points, at, j = [], start, 0
        while at <= end:
            while j < len(slots) and slots[j].end <= at:
                j += 1
            inside = j < len(slots) and slots[j].start <= at
            points.append(slots[j].export_kw if inside else None)
            at += timedelta(minutes=5)
        if sum(p is not None for p in points) < 0.8 * len(points):
            return None
        filled = [p if p is not None else 0.0 for p in points]
        return max(sum(filled[i : i + 12]) / 12 for i in range(max(1, len(filled) - 11)))

    # --- the decision ----------------------------------------------------------------------

    def decide(self, snap: Snapshot) -> Decision:
        # 1. Manufacturer protective heating: never interrupt or confuse it.
        if snap.manufacturer_heating:
            return Decision(HOLD, "manufacturer_protective_heating", 1)
        # 2. The owner.
        if snap.owner_override:
            return Decision(HOLD, "owner_override", 2)
        if snap.heater_state not in STATES:
            return Decision(HOLD, "heater_state_not_controlled", 2)
        if snap.holiday:
            return self._send(snap, OFF, "holiday", 2, {})
        if snap.override_12h:
            return self._send(snap, STORAGE, "12hr_override", 2, {})
        desired, reason, layer, plan = self._policy(snap)
        return self._send(snap, desired, reason, layer, plan)

    def _send(self, snap, desired, reason, layer, plan) -> Decision:
        if desired == snap.heater_state:
            return Decision(desired, reason, layer, None, plan)
        # 3. Cloud and command guards may only block a command, never choose one.
        if not snap.cloud_ready:
            return Decision(HOLD, "cloud_or_freshness_gate", 3, None, {**plan, "wanted": desired})
        if (
            snap.last_command_at is not None
            and snap.now - snap.last_command_at < self.s.command_spacing
        ):
            return Decision(HOLD, "command_spacing", 3, None, {**plan, "wanted": desired})
        payload = {
            OFF: "off",
            BASELINE: f"Manual:{self.s.baseline_c}",
            STORAGE: f"Manual:{self.s.storage_c}",
        }[desired]
        return Decision(desired, reason, layer, payload, plan)

    def _policy(self, snap: Snapshot):
        s, now = self.s, snap.now
        fresh = (
            snap.reading_c is not None
            and snap.reading_at is not None
            and now - snap.reading_at <= s.reading_max_age
        )
        # A stale or missing reading is assumed to be just above the baseline's
        # reheat point: storage then starts earlier, never later.
        reading = snap.reading_c if fresh else s.baseline_c - s.hysteresis_c
        would_heat = reading <= s.storage_c - s.hysteresis_c
        in_peak = self._kind(now) == "peak"
        peak = None if in_peak else self.next_peak(now)
        plan = {"reading_c": reading, "reading_fresh": fresh, "next_peak": peak}

        # 4. Peak (and the lead before it): measured solar only.
        if in_peak or (peak is not None and now >= peak - s.peak_lead):
            plan["mode"] = PEAK
            if snap.heater_state == STORAGE:
                if not self.meter_fresh(now):
                    return OFF, "peak_meter_unavailable", 4, plan
                if self.sustained(now, s.withdraw, lambda x: x[1] > s.peak_import_tolerance_kw):
                    return OFF, "peak_import_sustained", 4, plan
                if in_peak or self.sustained(now, s.qualify, lambda x: x[2] >= s.peak_start_kw):
                    return STORAGE, "peak_solar_continues", 4, plan
                return OFF, "peak_ahead_no_qualified_solar", 4, plan
            if would_heat and self.sustained(now, s.qualify, lambda x: x[2] >= s.peak_start_kw):
                return STORAGE, "peak_solar_qualified", 4, plan
            return OFF, "peak_no_grid_heating", 4, plan

        rate = self._rate_c_per_hour(snap.heating_c_per_hour)
        grid_rate = tariff_at(now, self.tariffs, s.tariff_clock).rate
        local = now.astimezone(HOBART)
        evening = (
            peak is not None
            and peak.astimezone(HOBART).date() == local.date()
            and peak.astimezone(HOBART).hour >= s.evening_peak_from_hour
        )
        hours = max(0.0, s.storage_c - reading) / rate if would_heat else 0.0
        if evening:
            latest = peak - s.finish_margin - timedelta(hours=hours)
            plan.update(heating_hours=round(hours, 2), latest_start=latest)
            if snap.heater_state == STORAGE:
                plan["mode"] = DEADLINE
                return STORAGE, "storage_until_peak", 5, plan
            if now >= latest and would_heat:
                plan["mode"] = DEADLINE
                available = (peak - s.finish_margin - now).total_seconds() / 3600
                if available < hours - 5 / 60:  # more than a poll-rounding shortfall
                    plan["expected_reading_at_peak"] = round(
                        reading + rate * max(0.0, available), 1
                    )
                    return STORAGE, "storage_target_may_be_missed", 5, plan
                return STORAGE, "storage_latest_start", 5, plan
            if local.hour >= s.daytime_from_hour:
                plan["mode"] = DEADLINE
                if not would_heat:
                    return snap.heater_state, "storage_satisfied", 5, plan
                if reading <= s.baseline_c - s.hysteresis_c:
                    return STORAGE, "storage_now_tank_low", 5, plan
                later = self.best_forecast_kw(snap.forecast, now + timedelta(minutes=30), latest)
                plan["best_forecast_kw"] = later
                if later is not None and later < s.solar_floor_kw:
                    return STORAGE, "storage_now_no_solar_forecast", 6, plan
                if self._solar_worth_it(now, grid_rate, lambda: later, optional=False, plan=plan):
                    return STORAGE, "storage_now_solar", 5, plan
                return snap.heater_state, "storage_waiting", 6, plan

        # Opportunity: weekday nights and weekends.
        plan["mode"] = OPPORTUNITY
        if snap.heater_state == STORAGE:
            if not self.meter_fresh(now) or self.sustained(
                now, s.withdraw, lambda x: x[2] < s.solar_floor_kw - s.solar_stop_margin_kw
            ):
                return BASELINE, "solar_opportunity_ended", 5, plan
            return STORAGE, "solar_opportunity_continues", 5, plan
        finish_by = None if peak is None else peak - s.finish_margin
        fits = finish_by is None or now + timedelta(hours=hours) <= finish_by
        if would_heat and fits:
            horizon = min(
                finish_by or now + timedelta(hours=12),
                datetime.combine(local.date(), datetime.max.time(), HOBART),
            )

            def later():
                best = self.best_forecast_kw(snap.forecast, now + timedelta(minutes=30), horizon)
                plan["best_forecast_kw"] = best
                return best

            if self._solar_worth_it(now, grid_rate, later, optional=True, plan=plan):
                return STORAGE, "solar_opportunity", 5, plan
        return BASELINE, "baseline", 5, plan

    def _solar_worth_it(self, now, grid_rate, later, *, optional: bool, plan) -> bool:
        """Measured solar has held at least the floor for the qualification time,
        heating now is no dearer than the best forecast hour later, and, for
        heat that is not otherwise needed, saves at least the margin on grid."""
        s = self.s
        if not self.sustained(now, s.qualify, lambda x: x[2] >= s.solar_floor_kw):
            return False
        typical = self.typical_available(now) or 0.0
        cost_now = self.mixed_cost(typical, grid_rate)
        plan["solar_kw"] = round(typical, 2)
        plan["cost_now"] = round(cost_now, 4)
        later_kw = later()  # forecast looked up only once measured solar qualifies
        if (
            later_kw is not None
            and self.mixed_cost(later_kw, grid_rate) < cost_now - PRICE_TOLERANCE
        ):
            plan["waiting_for"] = "better_solar_forecast_later"
            return False
        return not optional or cost_now <= grid_rate - s.optional_heat_margin
