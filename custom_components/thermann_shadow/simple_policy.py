"""One pure policy for OFF, baseline 45, normal storage 62 and optional solar 70.

The native thermostat controls the element. Fresh cloud status supplies the
reported setting/temperature; only a commissioned, fresh circuit meter verifies
physical heating. CT-free installations retain baseline and required off-peak
storage, with nominal physics used solely for conservative planning.

Owner holds and the explicit 12-hour 62-degree Override take precedence. Routine
peak heating is parked unless the user selects verified solar-only operation.
The single weekday planner meets the normal target before peak; a shared solar
qualification may select optional storage directly or as a later top-up when
useful heat exceeds its opportunity cost, standby allowance and switching margin.
Weekends retain baseline until one fresh measured PV report opens a comfort window
latched until 18:00, in which 62 is planned to a deadline. Small forecast
changes do not toggle an already qualified boost; measured loss/import withdraws
it. All sends still pass the separate executor and bridge guards.

No I/O or learning authority. Adaptive polling and historical calibration remain
advisory. OFF is a software setting, never proof of zero electrical consumption.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time
import math
from statistics import median

from .model import ELEMENT_KW, TANK_KWH_PER_C, Forecast, Tariff, tariff_at, tariff_zone
from zoneinfo import ZoneInfo
from .targets import NORMAL, TARGET_C, state_at, validate_roles
from .solar import IMPORT_TOLERANCE_KW, PROTECTIVE_REASONS, QUALIFY, SPACING, WITHDRAW

OFF, BASELINE, STORAGE, HOLD = "off", "baseline", "storage", "hold"
STATES = (OFF, BASELINE, NORMAL, STORAGE)
PEAK_NEVER = "Never schedule heating during peak"
PEAK_SOLAR = "Verified solar-only heating"
PEAK, DEADLINE, OPPORTUNITY = "peak", "deadline", "opportunity"
PRICE_TOLERANCE = 0.005  # $/kWh: a later window must beat "now" by this much
SLOT = timedelta(minutes=5)  # planning grid
MEASURED_SPAN = timedelta(minutes=30)  # the measured surplus stands in for the forecast
SCAN_STEP = timedelta(minutes=15)
SCAN_HORIZON = timedelta(days=4)
# Protective peak OFF only. Restarts, holiday and ordinary transitions still wait.
SPACING_EXEMPT_REASONS = PROTECTIVE_REASONS


@dataclass(frozen=True)
class PolicySettings:
    baseline_c: int = 45  # owner's agreed baseline (compliance note: SIMPLIFIED_STRATEGY.md §3)
    storage_c: int = 70
    normal_c: int = 62
    boost_enabled: bool = True
    peak_policy: str = PEAK_NEVER
    boost_useful_fraction: float = 0.9
    boost_min_saving: float = 0.10
    hysteresis_c: float = 8.0  # Thermann guide p9: reheats about 8 °C below the target
    element_kw: float = ELEMENT_KW
    kwh_per_c: float = TANK_KWH_PER_C
    feed_in_rate: float = 0.09276
    tariff_clock: str = "standard"
    time_zone: str = "Australia/Hobart"
    daytime_start: time = time(9)
    storage_ready: time = time(16)
    baseline_start: time = time(21)
    peak_start_kw: float = 3.3  # element 3.0 kW + 0.3 kW buffer
    peak_import_tolerance_kw: float = IMPORT_TOLERANCE_KW
    solar_floor_kw: float = 1.0  # least measured surplus for optional (weekend) heating
    optional_heat_margin: float = 0.02  # $/kWh saving needed for heat not otherwise needed
    pause_min_saving: float = 0.30  # $ a later window must save to justify a pause
    qualify: timedelta = QUALIFY
    withdraw: timedelta = WITHDRAW
    command_spacing: timedelta = SPACING
    # One decision tick (1 min) plus the bridge's pre-command refresh, POST and
    # the measured cloud readback (about 2-63 s, T3c).
    peak_lead: timedelta = timedelta(minutes=2)
    soft_target_margin: timedelta = timedelta(minutes=30)  # planning buffer, not a shutdown
    evening_peak_from_hour: int = 12  # a peak starting at/after this is an evening peak
    reading_max_age: timedelta = timedelta(minutes=75)
    meter_max_age: timedelta = timedelta(minutes=3)
    weekend_enabled: bool = True
    weekend_pv_kw: float = 0.5
    weekend_qualify: timedelta = timedelta(minutes=15)
    weekend_end: time = time(18)
    sunset_kw: float = 0.2
    sunset_delay: timedelta = timedelta(minutes=30)

    def __post_init__(self) -> None:
        validate_roles(self.baseline_c, self.normal_c, self.storage_c)
        if (
            self.peak_policy not in (PEAK_NEVER, PEAK_SOLAR)
            or not 0 <= self.boost_useful_fraction <= 1
        ):
            raise ValueError("policy_preferences_invalid")
        if self.peak_start_kw < self.element_kw or self.solar_floor_kw <= 0:
            raise ValueError("policy_solar_thresholds_invalid")
        if not timedelta(minutes=1) <= self.peak_lead <= self.command_spacing:
            raise ValueError("policy_peak_lead_invalid")
        if self.soft_target_margin <= self.peak_lead:
            raise ValueError("policy_soft_target_inside_peak_lead")


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
    # Precedence layers 2-3, decided by the existing controller and bridge.
    owner_override: bool = False
    holiday: bool = False
    override_12h: bool = False
    override_target_c: int = 62
    weekend_latched: bool = False
    weekend_ended: bool = False
    cloud_ready: bool = True
    heater_meter_valid: bool = False  # optional starts require explicit verified input
    ct_free_solar_valid: bool = False  # separately commissioned grid-only policy
    optional_start_quality: str | None = None
    optional_adoption_ready: bool = False  # genuine recent cloud state + exit guards
    optional_measurement_lost: bool = False  # latched intervening event, not latest value
    optional_cooldown_until: datetime | None = None
    protective_exit_pending: bool = False
    optional_session_active: bool = False
    measured_element_kw: float | None = None  # verified instantaneous ON power; never inference
    optional_allowed: bool = True
    learned_rates: dict[int, float] = field(default_factory=dict)
    required_export_kw: float | None = (
        None  # raw verified grid export, never inferred element credit
    )


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
        # (at, import_kw, available_kw, element_on); available EXCLUDES the element.
        self.samples: deque[tuple[datetime, float, float, bool]] = deque()
        self.pv_samples: deque[tuple[datetime, float]] = deque()
        self.surplus_reset_at: datetime | None = None
        self.import_reset_at: datetime | None = None
        # 0.16.2: unmeasured intervals (last measured report -> next measured
        # report) around a valueless meter report. They never vote; they pause
        # the export-qualification timer instead of resetting it.
        self.unmeasured: deque[tuple[datetime, datetime]] = deque()
        self._gap_start: datetime | None = None
        self._peak_cache: tuple[datetime, datetime | None, datetime] | None = None

    # --- local meter ---------------------------------------------------------------

    def add_pv(self, at, kw):
        """Independent production evidence; never substituted for grid surplus."""
        if at is None or kw is None or not math.isfinite(kw) or kw < 0:
            self.pv_samples.clear()
            return
        if self.pv_samples and at <= self.pv_samples[-1][0]:
            return
        self.pv_samples.append((at, kw))
        while self.pv_samples and at - self.pv_samples[0][0] > 2 * max(
            self.s.weekend_qualify, self.s.sunset_delay
        ):
            self.pv_samples.popleft()

    def pv_sustained(self, now, duration, predicate):
        recent = self._coverage(self.pv_samples, now, duration)
        return bool(recent) and all(predicate(p[1]) for p in recent)

    def _coverage(self, samples, now, duration):
        """Shortest genuine suffix spanning duration; no divisibility assumption.

        Anchor to the latest actual report, not an evaluation tick. Retain the
        first report at/before that boundary, including a failing reset sample.
        A stale/future latest report or any excessive gap invalidates coverage.
        """
        if not samples or not timedelta(0) <= now - samples[-1][0] <= self.s.meter_max_age:
            return []
        cutoff = samples[-1][0] - duration
        recent = []
        for sample in reversed(samples):
            if recent and recent[-1][0] - sample[0] > self.s.meter_max_age:
                return []
            recent.append(sample)
            if sample[0] <= cutoff:
                return list(reversed(recent))
        return []

    def pv_window_open(self, now) -> bool:
        """The latest PV report is fresh, genuine and at least the weekend start.

        One report is enough (0.17.0): no qualification period. Restored,
        invalid or stale reports never open the window.
        """
        if not self.pv_samples:
            return False
        at, kw = self.pv_samples[-1]
        return timedelta(0) <= now - at <= self.s.meter_max_age and kw >= self.s.weekend_pv_kw

    def _weekend(self, snap, reading, fresh, rate, plan, local, baseline, normal, boost):
        """Weekend comfort window (0.17.0).

        45 baseline until the first fresh measured PV report of at least the
        start power opens the window; it then stays latched until the end time
        (18:00), whatever the PV does. Inside it, 62 normal storage is planned
        economically against the storage-ready deadline using the published
        PV/household forecast, with off-peak grid assistance permitted. With no
        usable forecast it starts at once. If PV never opens the window and the
        tank needs heat, the latest start still meets the deadline. 70 uses the
        unchanged optional-boost test. At the end time the thermostat target
        returns to 45; that does not cool the stored water.
        """
        s, now, state = self.s, snap.now, snap.heater_state
        zone = ZoneInfo(s.time_zone)
        clock = local.time().replace(tzinfo=None)
        if snap.weekend_ended or clock >= s.weekend_end:
            plan.update(weekend_day_ended=True, mode=OPPORTUNITY)
            return baseline, "weekend_day_ended", 5, plan
        end = datetime.combine(local.date(), s.weekend_end, zone)
        service_at = datetime.combine(local.date(), s.storage_ready, zone)
        peak = plan.get("next_peak")
        if peak is not None:
            end = min(end, peak - s.soft_target_margin)
            service_at = min(service_at, peak)
        soft = service_at - s.soft_target_margin
        normal_rate = self._target_rate(snap, s.normal_c)
        would_heat = reading <= s.normal_c - s.hysteresis_c
        hours = (
            max(0, s.normal_c - reading) / normal_rate
            if would_heat or snap.measured_element_kw is not None
            else 0
        )
        latest = soft - timedelta(hours=hours)
        opened_by = (
            "latched"
            if snap.weekend_latched
            else "measured_pv"
            if self.pv_window_open(now)
            else "deadline_fallback"
            if would_heat and now >= latest
            else None
        )
        day_active = opened_by is not None
        plan.update(
            mode=OPPORTUNITY,
            next_baseline=datetime.combine(local.date(), s.weekend_end, zone),
            soft_target=soft,
            latest_start=latest,
            heating_hours=round(hours, 2),
        )
        if day_active:
            plan.update(
                weekend_day_latched=True,
                weekend_grid_assistance_permitted=True,
                weekend_window_opened_by=opened_by,
            )
        # An authorised 70 session does not need the original 3.3 kW export to
        # persist after the element starts consuming it. Withdrawal uses actual
        # import and meter liveness; return to underlying comfort, not OFF.
        if state == boost and boost != baseline:
            if self.importing_continuously(now):
                return (normal if day_active else baseline), "solar_opportunity_import", 5, plan
            if (
                s.boost_enabled
                and self.optional_measurement_valid(snap)
                and self.meter_fresh(now)
                and not self.importing_continuously(now)
            ):
                return boost, "solar_opportunity_continues", 5, plan
            return (normal if day_active else baseline), "solar_opportunity_ended", 5, plan
        eligible, info = self._boost(
            snap, reading, fresh, rate, end, s.normal_c if day_active else s.baseline_c
        )
        plan.update(info)
        if eligible:
            return boost, "solar_opportunity", 5, plan
        if not day_active:
            return baseline, "baseline", 5, plan
        # A selected 62 target is never paused: no command churn on weekends.
        if state == normal or (not would_heat and snap.measured_element_kw is None):
            # A thermostat request, not a claim the probe reached 62 or that
            # the element will energise.
            return normal, "weekend_daytime_storage", 5, plan
        if now >= latest:
            late = now + timedelta(hours=hours) > soft + SLOT
            return (
                normal,
                "storage_target_may_be_missed" if late else "storage_latest_start",
                5,
                plan,
            )
        if not snap.forecast:
            plan["waiting_for"] = "no_forecast_start_now"
            return normal, "weekend_storage_no_forecast", 5, plan
        measured = self.typical_available(now)
        profile = self.surplus_profile(
            now, soft, snap.forecast, measured if measured is not None else snap.required_export_kw
        )
        need = max(1, math.ceil(hours * 60 / 5))
        costs = self._windows(profile, self._prices(now, len(profile)), need)
        best = self._cheapest(costs)
        if best is None:
            return normal, "storage_latest_start", 5, plan
        plan.update(
            best_start=now + best * SLOT,
            cost_now=round(costs[0], 4),
            cost_best=round(costs[best], 4),
        )
        if best == 0:
            return normal, "storage_cheapest_now", 5, plan
        return baseline, "storage_waiting_for_cheaper_window", 5, plan

    def add_meter(
        self, at: datetime, grid_kw: float, element_on: bool | None = None, *, heater_kw=None
    ) -> None:
        """One local sample: grid import positive, export negative. ``element_on``
        is the caller's element estimate (house-load step); None counts as off,
        which can only make solar look SMALLER (never a costly start)."""
        if not math.isfinite(grid_kw) or (
            heater_kw is not None and not 0 <= heater_kw <= self.s.element_kw * 3.8 / 3
        ):
            self.samples.clear()
            return
        if self.samples and at <= self.samples[-1][0]:
            return  # the same HA report cannot become extra qualification votes
        if not self.samples:
            self._gap_start = None  # nothing measured before it to bridge
        elif self._gap_start is not None:
            self.unmeasured.append((self._gap_start, at))
            self._gap_start = None
        # Boolean input is retained for synthetic pure-policy tank simulations.
        # The runtime always supplies actual CT kW explicitly.
        measured = heater_kw if heater_kw is not None else self.s.element_kw if element_on else 0.0
        available = -grid_kw + measured
        self.samples.append(
            (at, max(0.0, grid_kw), available, measured >= self.s.element_kw * 2 / 3)
        )
        cutoff = at - 2 * max(self.s.qualify, self.s.withdraw)
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()
        while self.unmeasured and self.unmeasured[0][1] < cutoff:
            self.unmeasured.popleft()

    def note_missing(self) -> None:
        """A current meter report carried no value. It is never a vote: the
        time from the last measured report until the next one is unmeasured
        and does not count toward sustained export."""
        if self.samples and self._gap_start is None:
            self._gap_start = self.samples[-1][0]

    def _unmeasured_within(self, start: datetime, end: datetime) -> timedelta:
        """Exact length of the UNION of unmeasured intervals inside [start, end].

        Overlapping or adjacent intervals are merged first, so no unmeasured
        time is counted twice and none is missed.
        """
        clipped = sorted(
            (max(a, start), min(b, end)) for a, b in self.unmeasured if min(b, end) > max(a, start)
        )
        total, run_start, run_end = timedelta(0), None, None
        for a, b in clipped:
            if run_end is None or a > run_end:
                if run_end is not None:
                    total += run_end - run_start
                run_start, run_end = a, b
            else:
                run_end = max(run_end, b)
        if run_end is not None:
            total += run_end - run_start
        return total

    def _window(self, now: datetime, window: timedelta):
        return [smp for smp in self.samples if now - window <= smp[0] <= now]

    def meter_fresh(self, now: datetime) -> bool:
        return (
            bool(self.samples) and timedelta(0) <= now - self.samples[-1][0] <= self.s.meter_max_age
        )

    def sustained(self, now: datetime, window: timedelta, test) -> bool:
        """Legacy faded-solar majority check over a fully covered genuine span.

        Strict startup/import/PV timers below require every report to pass.
        """
        recent = self._coverage(self.samples, now, window)
        if not recent:
            return False
        if not (test(recent[0]) and test(recent[-1])):
            return False
        return sum(1 for smp in recent if test(smp)) >= 0.8 * len(recent)

    def typical_available(self, now: datetime) -> float | None:
        """Median measured surplus over the qualification window (fresh meter only)."""
        recent = self._window(now, self.s.qualify)
        if not recent or not self.meter_fresh(now):
            return None
        return median(smp[2] for smp in recent)

    def importing_continuously(self, now: datetime) -> bool:
        """Acceptable readings reset withdrawal; stale/gapped evidence cannot vote."""
        recent = self._coverage(self.samples, now, self.s.withdraw)
        return (
            bool(recent)
            and (self.import_reset_at is None or recent[0][0] > self.import_reset_at)
            and all(smp[1] > self.s.peak_import_tolerance_kw for smp in recent)
        )

    def surplus_qualified(self, now: datetime) -> bool:
        """At least ``qualify`` of MEASURED time with every report passing.

        Walk back from the latest report. Every report on the way must be
        genuine (no report gap over the meter age), after the last reset and
        at or above the start threshold. The window qualifies at the first
        report where elapsed time minus the exact union of unmeasured time
        reaches ``qualify``. There is no iteration limit: the walk is bounded
        by the retained reports, and running out of reports fails closed.
        """
        if (
            not self.samples
            or not timedelta(0) <= now - self.samples[-1][0] <= self.s.meter_max_age
        ):
            return False
        if self._gap_start is not None:
            return False  # a gap is still open: adequate evidence not established
        latest, newer = self.samples[-1][0], None
        for at, _import_kw, available, _element_on in reversed(self.samples):
            if newer is not None and newer - at > self.s.meter_max_age:
                return False
            if self.surplus_reset_at is not None and at <= self.surplus_reset_at:
                return False
            if available < self.s.peak_start_kw:
                return False
            measured = (latest - at) - self._unmeasured_within(at, latest)
            if measured >= self.s.qualify:
                return True
            newer = at
        return False

    @staticmethod
    def optional_measurement_valid(snap):
        return snap.heater_meter_valid or snap.ct_free_solar_valid

    # --- tariff calendar --------------------------------------------------------------

    def _kind(self, at: datetime) -> str:
        return tariff_at(at, self.tariffs, self.s.tariff_clock, self.s.time_zone).kind

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

    def _rate_c_per_hour(self, observed: float | None, measured_kw=None) -> float:
        # Slower measured watts advance a required start. Never assume faster
        # completion than nominal physics from a momentary high plateau.
        power = (
            min(self.s.element_kw, measured_kw)
            if measured_kw is not None
            and self.s.element_kw * 2 / 3 <= measured_kw <= self.s.element_kw * 3.8 / 3
            else self.s.element_kw
        )
        physics = power / self.s.kwh_per_c
        if observed is None or observed <= 0:
            return physics
        return min(max(observed, 0.5 * physics), 1.5 * physics)

    def _target_rate(self, snap, target):
        live_nominal = self._rate_c_per_hour(None, snap.measured_element_kw)
        if target in snap.learned_rates:
            return min(live_nominal, snap.learned_rates[target])
        return self._rate_c_per_hour(snap.heating_c_per_hour, snap.measured_element_kw)

    def mixed_cost(self, surplus_kw: float, grid_rate: float) -> float:
        """$/kWh of heat when ``surplus_kw`` of solar covers part of the element."""
        solar = min(max(surplus_kw, 0.0), self.s.element_kw)
        return (solar * self.s.feed_in_rate + (self.s.element_kw - solar) * grid_rate) / (
            self.s.element_kw
        )

    @staticmethod
    def surplus_profile(now, end, forecast, measured_kw: float | None) -> list[float]:
        """Expected surplus (kW) for each 5-minute slot in [now, end). The measured
        surplus stands in for the first 30 minutes; after that the EMHASS
        forecast. A slot the forecast does not cover counts as no surplus, so a
        missing forecast never makes waiting look cheaper."""
        slots = sorted(forecast, key=lambda f: f.start)
        starts = [f.start for f in slots]
        out, at = [], now
        while at < end:
            if measured_kw is not None and at - now < MEASURED_SPAN:
                out.append(measured_kw)
            else:
                mid = at + SLOT / 2
                j = bisect_right(starts, mid) - 1
                out.append(slots[j].export_kw if j >= 0 and slots[j].end > mid else 0.0)
            at += SLOT
        return out

    def _windows(self, profile: list[float], grid_rate: float | list[float], slots: int):
        """Mean $/kWh of each window of ``slots`` consecutive slots, by start index."""
        prefix = [0.0]
        for i, kw in enumerate(profile):
            prefix.append(
                prefix[-1]
                + self.mixed_cost(kw, grid_rate[i] if isinstance(grid_rate, list) else grid_rate)
            )
        return [(prefix[i + slots] - prefix[i]) / slots for i in range(len(profile) - slots + 1)]

    def _prices(self, now, count):
        return [
            tariff_at(now + i * SLOT, self.tariffs, self.s.tariff_clock, self.s.time_zone).rate
            for i in range(count)
        ]

    @staticmethod
    def _cheapest(costs: list[float], first: int = 0) -> int | None:
        """Earliest start from ``first`` whose cost no later start beats by more
        than the tolerance (ties go to the earliest: more slack, same price)."""
        best = None
        for i in range(first, len(costs)):
            if best is None or costs[i] < costs[best] - PRICE_TOLERANCE:
                best = i
        return best

    # --- the decision ----------------------------------------------------------------------

    def setpoint(self, state: str | None) -> int | None:
        """The Manual setpoint a policy state requests (None for OFF/unknown)."""
        return TARGET_C.get(state)

    def decide(self, snap: Snapshot) -> Decision:
        # 1. The heater's own protections are native in every state: nothing to decide.
        # 2. The owner.
        if snap.owner_override:
            return Decision(HOLD, "owner_override", 2)
        if snap.heater_state not in STATES:
            return Decision(HOLD, "heater_state_not_controlled", 2)
        if snap.holiday:
            return self._send(snap, OFF, "holiday", 2, {})
        if snap.override_12h:
            return self._send(snap, state_at(snap.override_target_c), "12hr_override", 2, {})
        desired, reason, layer, plan = self._policy(snap)
        # 3. Reserve the command slot for the peak transition: in the spacing
        # before the peak lead, send nothing that would need another command
        # (the park) at the boundary.
        peak = plan.get("next_peak")
        if (
            desired not in (OFF, snap.heater_state)
            and peak is not None
            and peak - self.s.peak_lead - self.s.command_spacing
            <= snap.now
            < peak - self.s.peak_lead
        ):
            return Decision(
                snap.heater_state, "peak_command_reserved", 3, None, {**plan, "wanted": desired}
            )
        return self._send(snap, desired, reason, layer, plan)

    def _send(self, snap, desired, reason, layer, plan) -> Decision:
        plan = {
            **plan,
            "planned_heat_kwh": round(
                max(0, (self.setpoint(desired) or 0) - plan.get("reading_c", self.s.baseline_c))
                * self.s.kwh_per_c,
                3,
            )
            if desired != OFF
            else 0,
            "desired_target_c": self.setpoint(desired),
            "planning_rate_c_per_hour": self._target_rate(snap, self.setpoint(desired))
            if desired != OFF
            else None,
            "planning_rate_basis": "learned_conservative_lower_bound"
            if self.setpoint(desired) in snap.learned_rates
            else "nominal_or_verified_live_watts",
            "heating_role": "owner_override"
            if reason == "12hr_override"
            else "park"
            if desired == OFF
            else "required"
            if plan.get("mode") == DEADLINE and desired == state_at(self.s.normal_c)
            else "weekend_comfort"
            if plan.get("weekend_day_latched") and desired == state_at(self.s.normal_c)
            else "baseline"
            if desired == state_at(self.s.baseline_c)
            else "optional",
        }
        spacing_exempt = desired == OFF and reason in SPACING_EXEMPT_REASONS
        if desired == snap.heater_state:
            return Decision(desired, reason, layer, None, plan)
        # 3. Cloud and command guards may only block a command, never choose one.
        if not snap.cloud_ready:
            return Decision(HOLD, "cloud_or_freshness_gate", 3, None, {**plan, "wanted": desired})
        if (
            not spacing_exempt
            and snap.last_command_at is not None
            and snap.now - snap.last_command_at < self.s.command_spacing
        ):
            return Decision(HOLD, "command_spacing", 3, None, {**plan, "wanted": desired})
        payload = "off" if desired == OFF else f"Manual:{self.setpoint(desired)}"
        return Decision(desired, reason, layer, payload, plan)

    def _boost(self, snap, reading, fresh, rate, end, reference_c, *, peak=False, target=None):
        """One optional-energy test; never a second heating planner."""
        s, now = self.s, snap.now
        goal = s.storage_c if target is None else target
        rate = self._target_rate(snap, goal)
        info = {
            "boost_eligible": False,
            "boost_reason": "disabled",
            "boost_extra_kwh": round(max(0, goal - max(reference_c, reading)) * s.kwh_per_c, 3),
        }

        def reject(reason):
            info["boost_reason"] = reason
            return False, info

        if not s.boost_enabled and target is None:
            return reject("boost_disabled")
        if snap.optional_start_quality is not None:
            return reject(snap.optional_start_quality)
        if goal <= reference_c:
            return reject("same_as_normal_target")
        if not snap.optional_allowed:
            return reject("optional_budget_reserved_for_essential_heat")
        if snap.protective_exit_pending:
            return reject("protective_exit_unresolved")
        if snap.optional_cooldown_until is not None and now < snap.optional_cooldown_until:
            return reject("solar_withdrawal_cooldown")
        if not self.optional_measurement_valid(snap) or not self.meter_fresh(now):
            return reject("verified_circuit_and_grid_required")
        if not fresh:
            return reject("fresh_temperature_required")
        if reading > goal - s.hysteresis_c and snap.measured_element_kw is None:
            return reject("inside_native_hysteresis_no_verified_heat")
        if not self.surplus_qualified(now):
            return reject("sustained_full_solar_required")
        hours = max(0, goal - reading) / rate
        if end is not None and now + timedelta(hours=hours) > end:
            return reject("boost_cannot_finish_before_peak")
        horizon = now + timedelta(hours=max(hours, SLOT.total_seconds() / 3600))
        profile = self.surplus_profile(now, horizon, snap.forecast, self.typical_available(now))
        later = min((t.rate for t in self.tariffs if t.kind != "peak"), default=0)
        price = tariff_at(now, self.tariffs, s.tariff_clock, s.time_zone).rate
        cost = sum(
            self.mixed_cost(kw, p)
            for kw, p in zip(profile, self._prices(now, len(profile)), strict=True)
        ) / len(profile)
        if peak:
            cost = self.mixed_cost(self.typical_available(now), price)
        extra = info["boost_extra_kwh"]
        # Explicit demand assumption and a bounded standby allowance. Neither
        # is learned evidence or permission to weaken measured import guards.
        use_hours = min(12, max(0, ((end - now).total_seconds() / 3600 if end else 12)))
        loss = extra * min(0.25, 0.01 * use_hours) * later
        saving = extra * s.boost_useful_fraction * later - extra * cost - loss
        info.update(
            boost_expected_saving_aud=round(saving, 4),
            boost_standby_allowance_aud=round(loss, 4),
            boost_useful_fraction=s.boost_useful_fraction,
            boost_cost_aud_per_kwh=round(cost, 4),
        )
        if saving < max(s.boost_min_saving, extra * s.optional_heat_margin):
            return reject("boost_value_below_switching_margin")
        info["boost_heating_hours"] = round(hours, 2)
        info.update(boost_eligible=True, boost_reason="useful_solar_value_exceeds_margin")
        return True, info

    def _policy(self, snap: Snapshot):
        s, now, state = self.s, snap.now, snap.heater_state
        baseline, normal, boost = (
            state_at(s.baseline_c),
            state_at(s.normal_c),
            state_at(s.storage_c),
        )
        fresh = (
            snap.reading_c is not None
            and snap.reading_at is not None
            and timedelta(0) <= now - snap.reading_at <= s.reading_max_age
        )
        reading = snap.reading_c if fresh else s.baseline_c - s.hysteresis_c
        rate = self._rate_c_per_hour(snap.heating_c_per_hour, snap.measured_element_kw)
        in_peak = self._kind(now) == "peak"
        peak = None if in_peak else self.next_peak(now)
        at_boundary = in_peak or (peak is not None and now >= peak - s.peak_lead)
        plan = {
            "reading_c": reading,
            "reading_fresh": fresh,
            "next_peak": peak,
            "setpoint_c": self.setpoint(state),
            "normal_target_c": s.normal_c,
            "boost_target_c": s.storage_c,
            "baseline_target_c": s.baseline_c,
            "storage_target_c": s.normal_c,
            "peak_heating_policy": s.peak_policy,
            "optional_boost_enabled": s.boost_enabled,
            "circuit_measurement_available": snap.heater_meter_valid,
            "solar_measurement_basis": "verified_circuit"
            if snap.heater_meter_valid
            else "commissioned_grid_only"
            if snap.ct_free_solar_valid
            else "unqualified",
            "optional_cooldown_until": snap.optional_cooldown_until,
            "current_import_price_aud": tariff_at(
                now, self.tariffs, s.tariff_clock, s.time_zone
            ).rate,
            "boost_eligible": False,
            "boost_reason": "not_qualified",
            "target_reached": fresh and reading >= s.normal_c,
            "thermostat_would_heat_at_storage": reading <= s.normal_c - s.hysteresis_c,
        }
        if at_boundary:
            plan["mode"] = PEAK
            # Lockout precedes all routine economics/forecast/solar decisions.
            # Explicit owner hold/override/12h Override were handled by decide.
            if s.peak_policy == PEAK_NEVER:
                plan["boost_reason"] = "peak_heating_locked_out"
                return OFF, "peak_lockout", 4, plan
            if snap.optional_measurement_lost:
                return OFF, "peak_meter_unavailable", 4, plan
            qualified = self.surplus_qualified(now)
            if state in (NORMAL, STORAGE):
                if not self.meter_fresh(now):
                    return OFF, "peak_meter_unavailable", 4, plan
                if not self.optional_measurement_valid(snap):
                    return OFF, "peak_heater_meter_unavailable", 4, plan
                carried_session = (
                    snap.optional_session_active
                    and self.samples[-1][1] <= s.peak_import_tolerance_kw
                )
                if not in_peak and not qualified and not carried_session:
                    return OFF, "peak_ahead_no_qualified_solar", 4, plan
                if not snap.optional_session_active and not qualified:
                    return OFF, "peak_no_qualified_session", 4, plan
                if self.importing_continuously(now):
                    return OFF, "peak_solar_withdrawn", 4, plan
                later = min((t.rate for t in self.tariffs if t.kind != "peak"), default=0)
                if s.feed_in_rate > later - s.optional_heat_margin:
                    return OFF, "peak_solar_uneconomic", 6, plan
                if fresh and reading >= s.storage_c:
                    return OFF, "peak_solar_no_useful_heat", 4, plan
                if not snap.optional_session_active:
                    # A required normal target is not an authorised peak solar
                    # session. Prefer a useful properly guarded top-up, otherwise
                    # qualify an in-place carry with the complete startup test.
                    if state == normal and boost != normal and s.boost_enabled:
                        eligible, info = self._boost(
                            snap, reading, fresh, rate, None, s.normal_c, peak=True
                        )
                        plan.update(info)
                        if eligible:
                            return boost, "peak_solar_qualified", 4, plan
                    eligible, info = self._boost(
                        snap,
                        reading,
                        fresh,
                        rate,
                        None,
                        s.baseline_c,
                        peak=True,
                        target=self.setpoint(state),
                    )
                    plan.update(info)
                    if not eligible or not snap.optional_adoption_ready:
                        if eligible:
                            plan["boost_reason"] = "fresh_cloud_state_for_adoption_required"
                        return OFF, "peak_no_qualified_session", 4, plan
                    plan["adopt_solar_session"] = True
                if not s.boost_enabled and state == STORAGE and normal != STORAGE:
                    return normal, "peak_normal_solar_only", 4, plan
                if (
                    snap.optional_session_active
                    and state == normal
                    and boost != normal
                    and s.boost_enabled
                ):
                    eligible, info = self._boost(
                        snap, reading, fresh, rate, None, s.normal_c, peak=True
                    )
                    plan.update(info)
                    if eligible:
                        return boost, "peak_solar_qualified", 4, plan
                return state, "peak_solar_continues", 4, plan
            goal = s.storage_c if s.boost_enabled else s.normal_c
            eligible, info = self._boost(
                snap, reading, fresh, rate, None, s.baseline_c, peak=True, target=goal
            )
            plan.update(info)
            if eligible:
                return state_at(goal), "peak_solar_qualified", 4, plan
            return OFF, "peak_no_grid_heating", 4, plan

        measured = self.typical_available(now)
        # Required off-peak heat can use the observed raw export without a CT.
        # This never enters optional qualification samples or credits nominal
        # element watts; a forecast/meter remains an estimate of future surplus.
        required_measured = measured if measured is not None else snap.required_export_kw
        price = tariff_at(now, self.tariffs, s.tariff_clock, s.time_zone).rate
        local = now.astimezone(ZoneInfo(s.time_zone))
        if local.weekday() >= 5 and s.weekend_enabled:
            return self._weekend(snap, reading, fresh, rate, plan, local, baseline, normal, boost)
        daytime = s.daytime_start <= local.time().replace(tzinfo=None)
        evening = (
            daytime
            and peak is not None
            and peak.astimezone(ZoneInfo(s.time_zone)).date() == local.date()
            and peak.astimezone(ZoneInfo(s.time_zone)).hour >= s.evening_peak_from_hour
        )
        # A flat or no-afternoon-peak day still has required weekday storage.
        # This is a service deadline, never an artificial peak/OFF boundary.
        clock_local = now.astimezone(tariff_zone(now, s.tariff_clock, s.time_zone))
        afternoon_peak_today = any(
            t.kind == "peak"
            and clock_local.month in t.months
            and clock_local.weekday() in t.days
            and (t.start >= 720 or t.end > 720 or t.start == t.end)
            for t in self.tariffs
        )
        flat_deadline = (
            daytime
            and local.time().replace(tzinfo=None) < s.baseline_start
            and local.weekday() < 5
            and not afternoon_peak_today
        )
        goal = s.normal_c if evening or flat_deadline else s.storage_c
        rate = self._target_rate(snap, goal)
        would_heat = reading <= goal - s.hysteresis_c
        # Actual ON evidence can continue toward target inside its hysteresis band.
        hours = (
            max(0, goal - reading) / rate
            if would_heat or snap.measured_element_kw is not None
            else 0
        )
        need = max(1, math.ceil(hours * 60 / 5))
        plan.update(heating_hours=round(hours, 2), measured_kw=measured)
        if evening or flat_deadline:
            plan["mode"] = DEADLINE
            service_at = (
                peak
                if evening
                else datetime.combine(local.date(), s.storage_ready, ZoneInfo(s.time_zone))
            )
            soft = service_at - s.soft_target_margin
            latest = soft - timedelta(hours=hours)
            plan.update(soft_target=soft, latest_start=latest)
            optional_end = (
                soft
                if evening
                else datetime.combine(local.date(), s.baseline_start, ZoneInfo(s.time_zone))
            )
            plan["next_baseline"] = datetime.combine(
                local.date(), s.baseline_start, ZoneInfo(s.time_zone)
            )
            eligible, info = self._boost(snap, reading, fresh, rate, optional_end, s.normal_c)
            plan.update(info)
            optional_running = state == boost and boost != normal
            if optional_running:
                withdrawn = (
                    not s.boost_enabled
                    or not self.optional_measurement_valid(snap)
                    or measured is None
                    or self.importing_continuously(now)
                )
                if not withdrawn:
                    return boost, "weekday_solar_boost_continues", 5, plan
                return normal, "weekday_solar_boost_withdrawn", 5, plan
            if eligible:
                return (
                    boost,
                    "weekday_direct_solar_boost" if state != normal else "weekday_solar_boost",
                    6,
                    plan,
                )
            if not would_heat and snap.measured_element_kw is None:
                reason = (
                    "storage_target_reached"
                    if plan["target_reached"]
                    else "storage_within_thermostat_band"
                )
                # Selecting normal is a thermostat request, not a claim that the
                # probe has reached it or that its element will energise.
                return (state if normal == STORAGE else normal), reason, 5, plan
            if now >= latest:
                if state == normal:
                    return normal, "storage_until_peak", 5, plan
                late = now + timedelta(hours=hours) > soft + SLOT
                return (
                    normal,
                    "storage_target_may_be_missed" if late else "storage_latest_start",
                    5,
                    plan,
                )
            profile = self.surplus_profile(now, soft, snap.forecast, required_measured)
            costs = self._windows(profile, self._prices(now, len(profile)), need)
            if state == normal:
                # Raw grid export includes an unknown element draw without a
                # commissioned circuit meter. It can choose a required start,
                # but cannot justify pausing an already selected normal target.
                if not snap.heater_meter_valid:
                    return normal, "storage_until_peak", 5, plan
                best = self._cheapest(costs, math.ceil(s.command_spacing / SLOT))
                if best is not None:
                    saving = (costs[0] - costs[best]) * hours * s.element_kw
                    plan.update(best_start=now + best * SLOT, pause_saving=round(saving, 2))
                    if saving >= s.pause_min_saving:
                        return OFF, "storage_paused_for_cheaper_window", 6, plan
                return normal, "storage_until_peak", 5, plan
            best = self._cheapest(costs)
            plan.update(
                best_start=now + best * SLOT,
                cost_now=round(costs[0], 4),
                cost_best=round(costs[best], 4),
            )
            if best == 0:
                if (
                    not snap.forecast
                    and costs[0] > price - PRICE_TOLERANCE
                    and max(costs) - costs[0] < PRICE_TOLERANCE
                ):
                    plan["waiting_for"] = "latest_start_no_forecast"
                    return state, "storage_waiting_no_forecast", 6, plan
                return normal, "storage_cheapest_now", 6, plan
            return state, "storage_waiting_for_cheaper_window", 6, plan

        plan["mode"] = OPPORTUNITY
        if state == boost and boost != baseline:
            if not s.boost_enabled or measured is None or not self.optional_measurement_valid(snap):
                return baseline, "solar_opportunity_ended", 5, plan
            if self.importing_continuously(now):
                return baseline, "solar_opportunity_import", 5, plan
            faded = self.sustained(now, s.withdraw, lambda x: x[2] < s.solar_floor_kw)
            ahead = self.surplus_profile(now, now + timedelta(hours=1), snap.forecast, None)
            returns = sum(ahead) / len(ahead) >= s.solar_floor_kw
            if faded and not returns and not snap.ct_free_solar_valid:
                return baseline, "solar_opportunity_ended", 5, plan
            return boost, "solar_opportunity_continues", 5, plan
        end = None if peak is None else peak - s.soft_target_margin
        eligible, info = self._boost(snap, reading, fresh, rate, end, s.baseline_c)
        plan.update(info)
        if eligible:
            return boost, "solar_opportunity", 5, plan
        return baseline, "baseline", 5, plan
